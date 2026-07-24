"""2C — repo-scale patch series: ranked, git-apply-able patches + REPORT.md."""
import subprocess
from pathlib import Path
from types import SimpleNamespace

from verto.engine.api import Engine
from verto.engine.config import Config
from verto.surfaces.patches import emit_patches

EX = Path(__file__).resolve().parent.parent / "examples"


def _fake(delta, transform, func, file="x.cpp"):
    return SimpleNamespace(
        accepted=True, udiff=f"--- a/{file}\n+++ b/{file}\n@@ -1 +1 @@\n-a\n+b\n",
        performance=SimpleNamespace(vector={"p50_delta_pct": delta}),
        correctness=SimpleNamespace(rung=3), via="harness",
        candidate=SimpleNamespace(transform=SimpleNamespace(name=transform, target_func=func)))


def test_ranks_by_measured_speedup(tmp_path):
    """Findings are ordered biggest-win-first and numbered accordingly."""
    results = [("a.cpp", [_fake(10.0, "reserve", "f")]),
               ("b.cpp", [_fake(80.0, "list_to_vector", "g")])]
    n, report = emit_patches(results, str(tmp_path))
    assert n == 2
    names = sorted(p.name for p in tmp_path.glob("*.patch"))
    assert names[0].startswith("0001-list_to_vector")     # 80% ranked first
    assert names[1].startswith("0002-reserve")
    body = Path(report).read_text()
    assert body.index("+80.0%") < body.index("+10.0%")    # ranked order in the table


def test_empty_run_writes_honest_report(tmp_path):
    n, report = emit_patches([("a.cpp", [])], str(tmp_path))
    assert n == 0 and "No verified wins" in Path(report).read_text()


def test_real_patch_applies(tmp_path):
    """End-to-end: a real accepted change emits a patch that `git apply --check` accepts."""
    vs = Engine(_cfg()).optimize(str(EX / "list_build.cpp"), apply=False)
    n, _ = emit_patches(vs, str(tmp_path), single_file=str(EX / "list_build.cpp"))
    assert n == 1
    patch = next(tmp_path.glob("*.patch"))
    assert patch.read_text().startswith("--- a/")
    r = subprocess.run(["git", "apply", "--check", "-p1", str(patch)],
                       cwd=EX.parent, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def _cfg():
    c = Config()
    c.model = "rules"
    return c


if __name__ == "__main__":
    import tempfile
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(Path(tempfile.mkdtemp())); print(f"  PASS {name}")
    print("ok")
