"""#12 cost cap — the Budget meter (tokens / money / time; per-run + per-hotspot)."""
from verto.runtime.budget import Budget, parse_spec


def test_parse_spec_units():
    assert parse_spec("500k") == (500_000, None, None)
    assert parse_spec("1M") == (1_000_000, None, None)
    assert parse_spec("500000") == (500_000, None, None)
    assert parse_spec("$2.5") == (None, 2.5, None)
    assert parse_spec("90s") == (None, None, 90.0)
    assert parse_spec("2min") == (None, None, 120.0)
    assert parse_spec("1h") == (None, None, 3600.0)
    assert parse_spec(None) == (None, None, None)


def test_no_budget_is_unlimited():
    b = Budget()
    b.charge(1_000_000, 1_000_000)
    assert b.can_spend()                     # no caps → always room, but still tracks
    assert b.spent()["tokens"] == 2_000_000


def test_run_token_cap():
    b = Budget(run_spec="1000")
    assert b.can_spend()
    b.charge(600, 300)                       # 900 total → still under
    assert b.can_spend()
    b.charge(100, 100)                       # 1100 total → over
    assert not b.can_spend()


def test_hotspot_cap_resets_per_function():
    b = Budget(run_spec="10000", hotspot_spec="500")
    b.start_hotspot()
    b.charge(300, 300)                       # 600 > 500 → this hotspot is done
    assert not b.can_spend()
    b.start_hotspot()                        # next function → the hotspot sub-limit resets
    assert b.can_spend()                     # the RUN cap (10000) still has room


def test_money_cap_and_pricing():
    b = Budget(run_spec="$10", price_in=3.0, price_out=15.0)   # $/1M tokens
    b.charge(1_000_000, 0)                    # $3
    assert b.can_spend()
    b.charge(0, 1_000_000)                    # +$15 = $18 > $10
    assert not b.can_spend()
    assert b.spent() == {"calls": 2, "tokens": 2_000_000, "usd": 18.0}


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
