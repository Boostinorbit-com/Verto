"""Map-lookup fusion — if(m.count(k)) … m.at(k) → one find() (2B-2).

Measure-first: the win is significant on std::map (tree walks, ~31-45%) and marginal on
unordered_map (cheap hashes). Where a map's order isn't observed, map→unordered_map is the
bigger win BOOSTOPT prefers — so this transform's niche is order-constrained std::map. The
tests force it in isolation via the --transforms filter.
"""
from pathlib import Path

from boostopt.adapters.language.cpp.regex_detect import detect_all_fuse, detect_fuse_in
from boostopt.adapters.language.cpp.transforms.fuse_map_lookup import FuseMapLookup
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

EX = Path(__file__).resolve().parent.parent / "examples"


def _cfg():
    c = Config()
    c.model = "rules"
    c.transforms = ("fuse_map_lookup",)          # isolate: else map→unordered preempts
    return c


def test_detects_count_at():
    src = (EX / "map_lookup.cpp").read_text()
    assert [s.func for s in detect_all_fuse(src)] == ["count_hits"]


def test_rewrite_is_a_single_find():
    src = (EX / "map_lookup.cpp").read_text()
    new, _ = FuseMapLookup().bind("count_hits").rewrite(src)
    assert "auto __vf_it = t.find(q);" in new
    assert "__vf_it != t.end()" in new
    assert "__vf_it->second" in new
    assert "if (t.count(q)) s += t.at(q);" not in new        # the double-lookup statement is gone


def test_mismatched_key_is_not_a_candidate():
    """count(a) but at(b) — different keys — must NOT fuse (would change behavior)."""
    src = ("#include <map>\nlong f(){ std::map<int,long> m; m[1]=1; int a=1,b=2;"
           " if(m.count(a)) return m.at(b); return -1; }")
    assert detect_fuse_in(src, "f") is None


def test_accepts_end_to_end():
    vs = Engine(_cfg()).optimize(str(EX / "map_lookup.cpp"), apply=False)
    acc = [v for v in vs if v.accepted]
    assert acc and acc[-1].candidate.transform.name == "fuse_map_lookup"
    assert acc[-1].correctness.rung >= 3
    assert acc[-1].performance.vector["p50_delta_pct"] > 2.0


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
