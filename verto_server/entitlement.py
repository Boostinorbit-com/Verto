"""The paywall — enforced SERVER-SIDE (VERTO_Tiers P4).

A `verto-token` maps to an Entitlement (plan + which features + which model + quota). The open
client never sees this logic; it just carries a token and gets 401/403 if it isn't entitled. So
the gate can't be bypassed by reading or forking the client.

STUBBED for the skeleton: an in-memory token dict. PRODUCTION replaces this with a real auth
store (API keys / OAuth), a database, and a metered quota — nothing else in this file changes.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Entitlement:
    plan: str                                   # "hosted-trial" | "pro" | "team" | "enterprise"
    features: frozenset = field(default_factory=frozenset)   # {"hosted-model","cleanroom","team"}
    model: str = "rules"                        # the proposer this plan gets — SERVER's choice
    llm_model: str = ""                         # the managed model name (server-side only)
    monthly_quota: int = 0                      # runs/month; 0 = unlimited (enterprise)


# ── STUB token store (production: a DB + real auth, NOT this dict) ────────────────────────────
_TOKENS = {
    # a free hosted trial — rules only, so it costs us ~nothing but demonstrates the seam
    "vt_demo_trial": Entitlement(plan="hosted-trial", features=frozenset({"hosted-model"}),
                                 model="rules", monthly_quota=100),
    # a paid plan maps to a MANAGED frontier model on our GPUs + clean-room benchmarking
    "vt_demo_pro":   Entitlement(plan="pro",
                                 features=frozenset({"hosted-model", "cleanroom"}),
                                 model="frontier", llm_model="verto-managed-coder",
                                 monthly_quota=5000),
}


def check(token: str | None) -> Entitlement | None:
    """`token` → Entitlement, or None if unknown/invalid. THE paywall (server-side).
    Production: DB lookup + real auth + decrement the metered quota here."""
    return _TOKENS.get((token or "").strip())


def has(ent: Entitlement | None, feature: str) -> bool:
    return ent is not None and feature in ent.features
