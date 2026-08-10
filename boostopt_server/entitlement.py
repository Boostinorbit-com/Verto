"""The paywall — enforced SERVER-SIDE (BOOSTOPT_Tiers P4).

Two halves, kept apart on purpose:

  • **POLICY** (this file): the PLAN CATALOG — each plan name → what it grants (features, which
    model, monthly quota). Change pricing here without touching a single account.
  • **DATA** (store.py): which *token* maps to which *plan*, plus metered usage — persisted.

A `boostopt-token` therefore resolves: token → Account (store) → plan → Entitlement (catalog). The
open client never sees any of this; it just carries a token and gets 401/403/429 if it isn't
entitled — so the gate can't be bypassed by reading or forking the client.

STILL a stand-in only in ONE place: a token is *created* by the admin CLI, not a payment webhook
(roadmap Phase 2.5). The lookup, features, quota, and metering are all real now.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .store import default_store


@dataclass(frozen=True)
class Entitlement:
    plan: str                                   # "hosted-trial" | "pro" | "team" | "enterprise"
    features: frozenset = field(default_factory=frozenset)   # {"hosted-model","cleanroom","team"}
    model: str = "rules"                        # the proposer this plan gets — SERVER's choice
    llm_model: str = ""                         # the managed model name (server-side only)
    monthly_quota: int = 0                      # runs/month; 0 = unlimited (enterprise)


# ── PLAN CATALOG (policy) — keyed by PLAN name, not by token ──────────────────────────────────
PLANS: dict[str, Entitlement] = {
    # a free hosted trial — rules only, so it costs us ~nothing but demonstrates the seam
    "hosted-trial": Entitlement(plan="hosted-trial", features=frozenset({"hosted-model"}),
                                model="rules", monthly_quota=100),
    # a paid plan → in PRODUCTION this maps to a managed FRONTIER model on our GPUs (+ clean-room).
    # in DEV we stub the model with the local coder (Ollama, CPU) so you see a REAL AI answer
    # through the hosted path with no GPU/API key. At release: model="frontier" + the real endpoint.
    "pro": Entitlement(plan="pro", features=frozenset({"hosted-model", "cleanroom"}),
                       model="local", llm_model="boostopt2.5-coder:7b", monthly_quota=5000),
}


def engine_label(ent: Entitlement) -> str:
    """A user-facing name for the engine this plan actually ran — so the CLI never mislabels it."""
    if ent.model == "rules":
        return "rules (dev stand-in — no AI)"
    who = "managed AI" if ent.model == "frontier" else "local AI"
    return f"{ent.llm_model or ent.model} ({who})"


def check(token: str | None) -> Entitlement | None:
    """`token` → Entitlement, or None if unknown/revoked/invalid. THE paywall (server-side).

    Resolves the token to an Account in the persistent store, then maps its plan to the catalog.
    Metering (the quota decrement) happens separately in the request path — see store.consume()."""
    acct = default_store().resolve(token)
    if acct is None:
        return None
    return PLANS.get(acct.plan)


def has(ent: Entitlement | None, feature: str) -> bool:
    return ent is not None and feature in ent.features
