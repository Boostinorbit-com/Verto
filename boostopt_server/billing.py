"""Stripe webhook → token issuance (PREMIUM — PRIVATE). Closes the money→token loop (roadmap 4.2/4.3).

Stripe calls `POST /v1/webhooks/stripe` when something billable happens. On a completed checkout we
mint a token via `store.issue()` and (production) email it to the buyer; on a cancelled
subscription we revoke it. This is the piece that turns "someone paid" into "someone has a
`--boostopt-token`" without a human in the loop.

What's REAL here vs a stand-in:
  • REAL — the Stripe **signature check** (HMAC-SHA256 over ``"{timestamp}.{payload}"``, the exact
    scheme Stripe uses); it just needs the real signing secret in ``$STRIPE_WEBHOOK_SECRET``.
  • REAL — the issue/revoke against the persistent store.
  • STUB — with no secret set we SKIP verification (dev convenience; the caller logs a loud warning).
  • STUB — the price→plan map is a small dict you fill with your real Stripe price IDs
    (``$STRIPE_PRICE_MAP='price_abc:pro,price_def:team'``), or set ``metadata.plan`` on the Checkout
    Session (preferred — unambiguous).
  • STUB — delivery: we LOG/return the token instead of emailing it. (Stripe ignores the response
    body anyway; at release, email `token` to the buyer and stop returning it.)

Swap those three at release; nothing else changes. No `stripe` SDK dependency — the signature and
event shape are handled with stdlib, matching boostopt_server's stdlib-first skeleton.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

from . import entitlement, store


class WebhookError(Exception):
    """A webhook that should be answered with a specific HTTP code (not a 500)."""
    def __init__(self, code: int, msg: str) -> None:
        super().__init__(msg)
        self.code = code
        self.msg = msg


# ── signature (the REAL Stripe scheme) ────────────────────────────────────────────────────────
def signing_secret() -> str:
    return os.environ.get("STRIPE_WEBHOOK_SECRET", "")


def _parse_sig_header(header: str) -> tuple[str | None, list[str]]:
    """`"t=169..,v1=abc,v1=def"` → (timestamp, [v1 signatures])."""
    ts: str | None = None
    v1: list[str] = []
    for part in header.split(","):
        if "=" not in part:
            continue
        k, val = part.split("=", 1)
        if k == "t":
            ts = val
        elif k == "v1":
            v1.append(val)
    return ts, v1


def sign_payload(payload: bytes, secret: str, ts: int) -> str:
    """Build a valid `Stripe-Signature` header for `payload` (used by tests + local dev)."""
    sig = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def verify_signature(payload: bytes, sig_header: str, secret: str, tolerance: int = 300) -> None:
    """Raise WebhookError(400) unless `sig_header` is a valid Stripe signature over `payload`.
    With no `secret` (dev), verification is SKIPPED — the caller must log that it did so."""
    if not secret:
        return                                              # dev: no secret configured → skip
    if not sig_header:
        raise WebhookError(400, "missing Stripe-Signature header")
    ts, v1 = _parse_sig_header(sig_header)
    if ts is None or not v1:
        raise WebhookError(400, "malformed Stripe-Signature header")
    try:
        if abs(time.time() - int(ts)) > tolerance:
            raise WebhookError(400, "timestamp outside tolerance (possible replay)")
    except ValueError:
        raise WebhookError(400, "bad timestamp in Stripe-Signature")
    expected = hmac.new(secret.encode(), f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, s) for s in v1):
        raise WebhookError(400, "signature verification failed")


# ── price → plan mapping (fill with your real Stripe price IDs) ────────────────────────────────
def _price_plan_map() -> dict[str, str]:
    out: dict[str, str] = {}
    for pair in os.environ.get("STRIPE_PRICE_MAP", "").split(","):
        if ":" in pair:
            pid, plan = pair.split(":", 1)
            out[pid.strip()] = plan.strip()
    return out


def _plan_from_session(obj: dict) -> str | None:
    """Prefer `metadata.plan` (set when the Checkout Session is created — unambiguous); otherwise
    map the line-item price id via $STRIPE_PRICE_MAP."""
    plan = (obj.get("metadata") or {}).get("plan")
    if plan:
        return plan
    items = (obj.get("line_items") or {}).get("data") or [{}]
    price = (items[0].get("price") or {}).get("id")
    return _price_plan_map().get(price) if price else None


# ── event dispatch ────────────────────────────────────────────────────────────────────────────
def handle_event(event: dict) -> dict:
    """Act on a parsed Stripe event. Returns a small dict describing what happened (for the log +
    the dev response). Unhandled event types are a no-op with 200 (Stripe best practice)."""
    etype = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}

    if etype == "checkout.session.completed":
        plan = _plan_from_session(obj)
        if not plan or plan not in entitlement.PLANS:
            raise WebhookError(400, f"no known BOOSTOPT plan for this checkout (plan={plan!r}); "
                                    f"set metadata.plan or $STRIPE_PRICE_MAP")
        email = obj.get("customer_email") or (obj.get("customer_details") or {}).get("email") or ""
        acct = store.default_store().issue(plan, note=email or "stripe")
        # PRODUCTION: email acct.token to `email`; do NOT return it in the webhook response.
        return {"handled": etype, "issued": True, "plan": plan, "email": email,
                "token": acct.token}

    if etype == "customer.subscription.deleted":
        # PRODUCTION needs a customer_id→token index; the stub revokes via metadata.boostopt_token.
        token = (obj.get("metadata") or {}).get("boostopt_token")
        revoked = store.default_store().revoke(token) if token else False
        return {"handled": etype, "revoked": revoked, "token": token}

    return {"handled": None, "ignored": etype}
