"""std::list → std::vector transform (2B-1, the cList-shaped case).

A std::list grown only at the back and iterated is behavior-equivalent to std::vector but
pays a heap node + pointer-chase per element (~20× slower to build+iterate). The transform
REFUSES any list-only op (push_front/splice/…) so the swap stays sound; the gate backstops.
"""
from pathlib import Path

from boostopt.adapters.language.cpp.regex_detect import detect_all_list
from boostopt.adapters.language.cpp.transforms.list_to_vector import ListToVector
from boostopt.engine.api import Engine
from boostopt.engine.config import Config

EX = Path(__file__).resolve().parent.parent / "examples"


def _cfg():
    c = Config()
    c.model = "rules"
    return c


def test_detects_backonly_list():
    src = (EX / "list_build.cpp").read_text()
    sites = detect_all_list(src)
    assert [(s.func, s.var, s.elem) for s in sites] == [("list_sum", "xs", "long")]


def test_rewrite_swaps_type_and_adds_header():
    src = (EX / "list_build.cpp").read_text()
    new, _patch = ListToVector().bind("list_sum").rewrite(src)
    assert "std::vector<long> xs;" in new
    assert "#include <vector>" in new


def test_push_front_is_refused():
    """push_front relies on O(1) front insertion vector lacks → must NOT be a candidate."""
    src = ("#include <list>\nint f(int n){ std::list<int> x;"
           " for(int i=0;i<n;i++) x.push_front(i); int s=0; for(int v:x) s+=v; return s; }")
    assert detect_all_list(src) == []


def test_splice_is_refused():
    src = ("#include <list>\nvoid f(){ std::list<int> a,b; a.push_back(1);"
           " b.splice(b.end(), a); }")
    assert detect_all_list(src) == []


def test_accepts_end_to_end():
    vs = Engine(_cfg()).optimize(str(EX / "list_build.cpp"), apply=False)
    acc = [v for v in vs if v.accepted]
    assert acc and acc[-1].candidate.transform.name == "list_to_vector"
    assert acc[-1].correctness.rung >= 3


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
