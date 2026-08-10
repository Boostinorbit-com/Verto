#!/usr/bin/env bash
# BOOSTOPT — end-to-end self-check. Runs the real engine on the example C++ files.
# Usage:  ./check.sh          (from anywhere)
set -u

# resolve repo root (this script's dir) so it works from any cwd
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT" || exit 2
export PYTHONPATH="$ROOT"

bold() { printf "\033[1m%s\033[0m\n" "$1"; }
rule() { printf '%s\n' "------------------------------------------------------------"; }
PY=python3

command -v "$PY"      >/dev/null || { echo "python3 not found"; exit 2; }
command -v clang++    >/dev/null || echo "warning: clang++ not found (builds will fail)"
command -v g++        >/dev/null || echo "warning: g++ not found (sanitizer fallback unavailable)"

# ---------------------------------------------------------------------------
bold "1) Transform demos  (real compile + differential test + ASan/UBSan + benchmark)"
rule
for f in packet_stats map_safe map_ordered; do
  rm -f "$ROOT/ledger.jsonl"
  printf "\n== examples/%s.cpp ==\n" "$f"
  "$PY" -m boostopt.surfaces.cli optimize "examples/$f.cpp" --offline
done
echo
echo "expected:  packet_stats → ACCEPT reserve (~-68%)"
echo "           map_safe     → ACCEPT map→unordered_map (~-90%)"
echo "           map_ordered  → REJECT (changed_output)   [ordering observed]"

# ---------------------------------------------------------------------------
echo
bold "2) Detection is AST-driven (libclang), not the regex fallback"
rule
"$PY" - <<'PY'
from boostopt.adapters.language.cpp import _ast
from pathlib import Path
for f in ["examples/packet_stats.cpp", "examples/map_safe.cpp", "examples/map_ordered.cpp"]:
    src = Path(f).read_text()
    g, m = _ast.growth_ast(src), _ast.map_ast(src)
    tag = "growth" if g else ("map" if m else "NONE")
    print(f"   {f.split('/')[-1]:22} AST → {tag}")
PY

# ---------------------------------------------------------------------------
echo
bold "3) Gate invariant  (accept ⟺ correct ∧ faster)"
rule
"$PY" - <<'PY'
import tests.engine.test_gate as t
t.test_accepts_correct_and_faster()
t.test_rejects_unsafe_even_if_faster()
t.test_rejects_slower_even_if_correct()
print("   gate: 3/3 passed  (accept⟺correct∧faster · UB→reject(unsafe) · slow→reject(slower))")
PY

# ---------------------------------------------------------------------------
echo
bold "4) Crown jewel  (sanitizer catches UB that PASSES the differential test)"
rule
"$PY" - <<'PY'
from boostopt.engine.config import Config
from boostopt.engine.models import Target, Variant
from boostopt.adapters.domain.performance.correctness import PerfCorrectnessOracle
from boostopt.adapters.domain.performance.inputs import HeldOutInputs
cfg = Config()
orig = Target(file="examples/packet_stats.cpp", symbol="build_histogram", line=5, language="cpp")
ub = '''#include <vector>
#include <cstddef>
std::vector<int> build_histogram(std::size_t n){
  std::vector<int> out; out.reserve(n);
  for(std::size_t i=0;i<n;++i) out.emplace_back((int)(i*2));
  if(n>0){volatile int s=out.data()[out.size()];(void)s;}   // one past end (UB)
  return out;
}'''
v = PerfCorrectnessOracle(cfg).equivalent(orig, Variant(orig, "", ub), HeldOutInputs(cfg))
print(f"   passed diff-test: {v.passed}   rung: {v.rung}")
print(f"   witness: {v.witness.sanitizer[:64]}")
print("   verdict:", "REJECT (unsafe)" if v.rung < cfg.min_rung else "ACCEPT")
assert v.passed and v.rung < cfg.min_rung, "expected: diff-test passes but sanitizer rejects"
print("   ✓ change that PASSES differential testing is REJECTED by the sanitizer")
PY

# rm -f "$ROOT/ledger.jsonl"
echo
bold "All checks complete."
