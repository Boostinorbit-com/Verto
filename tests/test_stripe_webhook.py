"""Phase 2 — Stripe webhook → token issuance (verto_server, PREMIUM).

Covers the money→token loop: the REAL Stripe signature scheme (accept valid / reject forged,
stale, missing), and event dispatch (paid checkout mints a resolvable token; cancellation revokes;
unknown plans 400; unknown events are ignored). Store is isolated per test via $VERTO_SERVER_DATA.
"""
from __future__ import annotations

import json
import time

import pytest

from verto_server import billing, entitlement, store


@pytest.fixture(autouse=True)
def _isolate_store(monkeypatch, tmp_path):
    monkeypatch.setenv("VERTO_SERVER_DATA", str(tmp_path / "srv"))
    monkeypatch.delenv("STRIPE_PRICE_MAP", raising=False)
    store.reset_store()
    yield
    store.reset_store()


def _event(etype: str, obj: dict) -> bytes:
    return json.dumps({"type": etype, "data": {"object": obj}}).encode("utf-8")


# ── signature (the real Stripe scheme) ────────────────────────────────────────────────────────
def test_valid_signature_passes():
    secret, payload = "whsec_test", b'{"hello":"world"}'
    header = billing.sign_payload(payload, secret, int(time.time()))
    billing.verify_signature(payload, header, secret)          # must not raise


def test_forged_signature_rejected():
    secret, payload = "whsec_test", b'{"hello":"world"}'
    header = billing.sign_payload(payload, "wrong_secret", int(time.time()))
    with pytest.raises(billing.WebhookError) as e:
        billing.verify_signature(payload, header, secret)
    assert e.value.code == 400


def test_tampered_payload_rejected():
    secret = "whsec_test"
    header = billing.sign_payload(b'{"amount":10}', secret, int(time.time()))
    with pytest.raises(billing.WebhookError):
        billing.verify_signature(b'{"amount":9999}', header, secret)   # body changed after signing


def test_stale_timestamp_rejected():
    secret, payload = "whsec_test", b"{}"
    header = billing.sign_payload(payload, secret, int(time.time()) - 10_000)
    with pytest.raises(billing.WebhookError):
        billing.verify_signature(payload, header, secret, tolerance=300)


def test_missing_signature_rejected_when_secret_set():
    with pytest.raises(billing.WebhookError):
        billing.verify_signature(b"{}", "", "whsec_test")


def test_no_secret_skips_verification():
    billing.verify_signature(b"{}", "", "")                    # dev mode: no secret → no raise


# ── event dispatch ────────────────────────────────────────────────────────────────────────────
def test_checkout_completed_issues_resolvable_token():
    event = json.loads(_event("checkout.session.completed",
                              {"customer_email": "alice@example.com", "metadata": {"plan": "pro"}}))
    result = billing.handle_event(event)
    assert result["issued"] and result["plan"] == "pro"
    tok = result["token"]
    ent = entitlement.check(tok)                               # the freshly-minted token works
    assert ent is not None and ent.plan == "pro"
    acct = store.default_store().resolve(tok)
    assert acct.note == "alice@example.com"                    # buyer recorded for support


def test_plan_from_price_map_when_no_metadata(monkeypatch):
    monkeypatch.setenv("STRIPE_PRICE_MAP", "price_abc123:pro")
    event = json.loads(_event("checkout.session.completed",
                              {"line_items": {"data": [{"price": {"id": "price_abc123"}}]}}))
    assert billing.handle_event(event)["plan"] == "pro"


def test_unknown_plan_is_400():
    event = json.loads(_event("checkout.session.completed", {"metadata": {"plan": "diamond"}}))
    with pytest.raises(billing.WebhookError) as e:
        billing.handle_event(event)
    assert e.value.code == 400


def test_subscription_deleted_revokes():
    acct = store.default_store().issue("pro", note="bob@example.com")
    assert entitlement.check(acct.token) is not None
    event = json.loads(_event("customer.subscription.deleted",
                              {"metadata": {"verto_token": acct.token}}))
    result = billing.handle_event(event)
    assert result["revoked"] is True
    assert entitlement.check(acct.token) is None              # revoked → paywall now refuses it


def test_unknown_event_is_ignored_not_errored():
    result = billing.handle_event(json.loads(_event("invoice.paid", {})))
    assert result["handled"] is None and result["ignored"] == "invoice.paid"
