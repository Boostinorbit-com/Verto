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
    # a paid plan → in PRODUCTION this maps to a managed FRONTIER model on our GPUs (+ clean-room).
    # in DEV we stub it with the local coder model (Ollama, CPU) so you see a REAL AI answer through
    # the hosted path with no GPU/API key. At release: model="frontier" + the real endpoint.
    "vt_demo_pro":   Entitlement(plan="pro",
                                 features=frozenset({"hosted-model", "cleanroom"}),
                                 model="local", llm_model="verto2.5-coder:7b",
                                 monthly_quota=5000),
}


def engine_label(ent: Entitlement) -> str:
    """A user-facing name for the engine this plan actually ran — so the CLI never mislabels it."""
    if ent.model == "rules":
        return "rules (dev stand-in — no AI)"
    who = "managed AI" if ent.model == "frontier" else "local AI"
    return f"{ent.llm_model or ent.model} ({who})"


def check(token: str | None) -> Entitlement | None:
    """`token` → Entitlement, or None if unknown/invalid. THE paywall (server-side).
    Production: DB lookup + real auth + decrement the metered quota here."""
    return _TOKENS.get((token or "").strip())


def has(ent: Entitlement | None, feature: str) -> bool:
    return ent is not None and feature in ent.features
