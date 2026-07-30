"""Persistent account + usage store for verto_server (PREMIUM — PRIVATE, never published).

This is the real plumbing for roadmap **Phase 2 (accounts & billing)**. It replaces the in-memory
token dict with a JSON-file-backed store, so:

  • tokens **survive restarts** (a real account, not a hard-coded constant), and
  • every run is **metered** — counted per billing period and capped at the plan's monthly quota.

The ONLY stand-in left is *how a token comes to exist*: here an operator runs the admin CLI
(`python -m verto_server.admin issue --plan pro`) instead of a Stripe webhook. At release the
payment provider calls `issue()` and nothing else in this file changes — same interface.

Deliberately NOT a database and NOT multi-process safe: a threading lock guards the single-process
dev server; the on-disk write is atomic (temp-file + replace). Production swaps the backend
(SQLite/Postgres) behind this same small surface. See verto_server/README.md.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def _period() -> str:
    """Current billing period key — the calendar month, e.g. ``'2026-07'``."""
    return time.strftime("%Y-%m")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


@dataclass
class Account:
    """One issued token and its metered usage. `plan` names an entry in entitlement.PLANS —
    the plan (features/model/quota) is looked up there, so a plan can be re-priced without
    rewriting every account."""
    token: str
    plan: str
    active: bool = True
    created: str = ""
    note: str = ""                                  # free-text: who this was issued to
    usage: dict = field(default_factory=dict)       # {period: run_count}, e.g. {"2026-07": 12}

    def used_this_period(self) -> int:
        return int(self.usage.get(_period(), 0))


class AccountStore:
    """Token → Account, persisted to one JSON file. All mutations take the lock and re-save."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._accounts: dict[str, Account] = {}
        self._load()

    # ── persistence ──────────────────────────────────────────────────────────────────────────
    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._accounts = {t: Account(**a) for t, a in raw.items()}
        else:                                        # first run → seed the demo tokens, then persist
            self._seed()
            self._save()

    def _seed(self) -> None:
        """The two demo tokens, so existing dev flows keep working after the store lands.
        (Production ships an EMPTY store — real tokens arrive via issue() on payment.)"""
        self._accounts = {
            "vt_demo_trial": Account(token="vt_demo_trial", plan="hosted-trial",
                                     created=_now(), note="seeded demo trial"),
            "vt_demo_pro": Account(token="vt_demo_pro", plan="pro",
                                   created=_now(), note="seeded demo pro"),
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps({t: asdict(a) for t, a in self._accounts.items()}, indent=2),
                       encoding="utf-8")
        tmp.replace(self._path)                      # atomic: never leaves a half-written file

    # ── reads ────────────────────────────────────────────────────────────────────────────────
    def resolve(self, token: str | None) -> Account | None:
        """Active account for `token`, else None (unknown or revoked)."""
        with self._lock:
            a = self._accounts.get((token or "").strip())
            return a if a and a.active else None

    def usage(self, token: str | None) -> tuple[int, str]:
        """(runs used this period, period key) — 0 if the token is unknown."""
        a = self.resolve(token)
        return (a.used_this_period() if a else 0, _period())

    def all_accounts(self) -> list[Account]:
        with self._lock:
            return list(self._accounts.values())

    # ── metering ─────────────────────────────────────────────────────────────────────────────
    def consume(self, token: str | None, quota: int, n: int = 1) -> tuple[bool, int, int]:
        """Reserve `n` runs for the current period. Returns ``(ok, used, quota)``.

        `quota` is the plan's monthly cap (passed in by the caller so this module stays free of
        plan policy); ``quota == 0`` means unlimited. When over quota, DOES NOT count — returns
        ``(False, used, quota)`` so the caller answers 429 without burning a run."""
        with self._lock:
            a = self.resolve(token)
            if a is None:
                return (False, 0, quota)
            used = a.used_this_period()
            if quota and used + n > quota:
                return (False, used, quota)          # over — reject, do not increment
            a.usage[_period()] = used + n
            self._save()
            return (True, used + n, quota)

    # ── admin mutations (used by admin.py / a future billing webhook) ─────────────────────────
    def issue(self, plan: str, note: str = "") -> Account:
        """Mint a fresh token for `plan` and persist it. In production the payment provider calls
        this; in dev the admin CLI does. Returns the new Account (its `.token` is the secret)."""
        token = "vt_" + secrets.token_urlsafe(24)
        with self._lock:
            acct = Account(token=token, plan=plan, created=_now(), note=note)
            self._accounts[token] = acct
            self._save()
            return acct

    def revoke(self, token: str) -> bool:
        """Deactivate a token (keeps its usage history). True if it existed."""
        with self._lock:
            a = self._accounts.get((token or "").strip())
            if a is None:
                return False
            a.active = False
            self._save()
            return True


# ── module singleton (the server's one store) ────────────────────────────────────────────────
_STORE: AccountStore | None = None


def _default_path() -> Path:
    """Where accounts live. Override with $VERTO_SERVER_DATA (a directory); default ~/.verto_server."""
    base = os.environ.get("VERTO_SERVER_DATA") or str(Path.home() / ".verto_server")
    return Path(base) / "accounts.json"


def default_store() -> AccountStore:
    global _STORE
    if _STORE is None:
        _STORE = AccountStore(_default_path())
    return _STORE


def reset_store() -> None:
    """Drop the cached singleton so the next call re-reads $VERTO_SERVER_DATA (for tests)."""
    global _STORE
    _STORE = None
