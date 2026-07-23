"""Seeded fuzzed correctness inputs (Phase-1 item #7).

The differential test keeps its hand-picked edge cases and adds `fuzz_inputs`
seeded-random sizes — deterministic (reproducible verdict), and bounded (cheap).
"""
from verto.adapters.domain.performance.inputs import HeldOutInputs, _EDGES
from verto.engine.config import Config


def _cfg(fuzz, seed=0):
    c = Config()
    c.fuzz_inputs = fuzz
    c.seed = seed
    return c


def test_edges_always_present():
    for fuzz in (0, 50, 1000):
        vals = HeldOutInputs(_cfg(fuzz)).values()
        for e in _EDGES:
            assert e in vals, f"edge {e} must always be tested (fuzz={fuzz})"


def test_fuzz_count_and_zero():
    assert HeldOutInputs(_cfg(0)).values() == _EDGES        # off → just the edges
    assert len(HeldOutInputs(_cfg(200)).values()) == len(_EDGES) + 200


def test_deterministic_by_seed():
    a = HeldOutInputs(_cfg(500, seed=7)).values()
    b = HeldOutInputs(_cfg(500, seed=7)).values()
    c = HeldOutInputs(_cfg(500, seed=8)).values()
    assert a == b, "same seed → identical inputs (reproducible verdict)"
    assert a != c, "different seed → different inputs"


def test_bounded_sizes():
    vals = HeldOutInputs(_cfg(2000)).values()
    assert max(vals) <= 65_536 and min(vals) >= 0        # nothing runaway


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  PASS {name}")
    print("all input tests passed")
