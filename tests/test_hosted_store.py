"""Phase 2 — persistent account store + quota metering (verto_server, PREMIUM).

Verifies the paywall data layer that replaced the in-memory token dict: token→plan resolution,
per-period metering with a hard cap, revoke, issue, and on-disk persistence across restarts.
Everything is isolated to a per-test $VERTO_SERVER_DATA dir so nothing touches ~/.verto_server.
"""
from __future__ import annotations

import pytest

from verto_server import entitlement, store


@pytest.fixture(autouse=True)
def _isolate_store(monkeypatch, tmp_path):
    """Point the store at a throwaway dir and drop the cached singleton for each test."""
    monkeypatch.setenv("VERTO_SERVER_DATA", str(tmp_path / "srv"))
    store.reset_store()
    yield
    store.reset_store()


def test_seeds_demo_tokens_on_first_run():
    tokens = {a.token for a in store.default_store().all_accounts()}
    assert {"vt_demo_trial", "vt_demo_pro"} <= tokens


def test_check_resolves_token_to_plan_entitlement():
    ent = entitlement.check("vt_demo_pro")
    assert ent is not None and ent.plan == "pro"
    assert "cleanroom" in ent.features and ent.monthly_quota == 5000


def test_check_rejects_unknown_token():
    assert entitlement.check("vt_not_a_real_token") is None
    assert entitlement.check("") is None
    assert entitlement.check(None) is None


def test_consume_meters_and_caps_at_quota():
    s = store.default_store()
    # first three within a cap of 3 succeed; the fourth is refused and does NOT increment
    assert [s.consume("vt_demo_trial", quota=3)[0] for _ in range(3)] == [True, True, True]
    ok, used, quota = s.consume("vt_demo_trial", quota=3)
    assert ok is False and used == 3 and quota == 3
    # a refused run left the counter where it was
    assert s.usage("vt_demo_trial")[0] == 3


def test_quota_zero_is_unlimited():
    s = store.default_store()
    assert all(s.consume("vt_demo_pro", quota=0)[0] for _ in range(50))


def test_revoke_blocks_resolution_and_consume():
    s = store.default_store()
    assert s.revoke("vt_demo_trial") is True
    assert entitlement.check("vt_demo_trial") is None
    assert s.consume("vt_demo_trial", quota=100)[0] is False
    assert s.revoke("vt_demo_trial_nope") is False


def test_issue_mints_a_usable_token():
    s = store.default_store()
    acct = s.issue("pro", note="alice@example.com")
    assert acct.token.startswith("vt_") and acct.plan == "pro"
    ent = entitlement.check(acct.token)
    assert ent is not None and ent.plan == "pro"


def test_usage_and_revoke_persist_across_restart():
    store.default_store().consume("vt_demo_pro", quota=5000)
    store.default_store().revoke("vt_demo_trial")
    store.reset_store()                       # simulate a server restart (re-read from disk)
    fresh = store.default_store()
    assert fresh.usage("vt_demo_pro")[0] == 1
    assert fresh.resolve("vt_demo_trial") is None


def test_period_isolated_counts():
    """Usage is keyed per period, so a prior month's runs don't count against this month."""
    s = store.default_store()
    acct = s.resolve("vt_demo_pro")
    acct.usage["2020-01"] = 999               # stale prior-period usage
    used, _ = s.usage("vt_demo_pro")
    assert used == 0                          # this period is still clean
    assert s.consume("vt_demo_pro", quota=1)[0] is True
