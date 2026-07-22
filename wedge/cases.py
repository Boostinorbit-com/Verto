"""Pre-registered Wedge cases (WEDGE_TEST.md). Committed BEFORE running.

Two kinds:
  - "pipeline": run `verto optimize <file>` and check the verdict (does VERTO find
    and verify the optimization, or correctly find nothing / reject it?).
  - "gate": feed VERTO's trusted gate an (original, plausible-but-wrong variant)
    pair — the kind a tests-only tool would accept — and check it REJECTS.
  - "pending": a category the engine doesn't implement yet; shown honestly.
"""
from __future__ import annotations

from dataclasses import dataclass

EX = "examples"
WD = "wedge/cases"


@dataclass
class Case:
    id: str
    category: str
    kind: str                 # pipeline | gate | pending
    expect: str               # accept | reject | none  (pipeline/gate)
    gap: str                  # why a competitor structurally fails / note
    file: str = ""
    symbol: str = ""          # gate cases: function under test
    variant: str = ""         # gate cases: the bad-optimization source
    reason: str = ""          # expected reject-reason substring
    expect_symbol: str = ""   # pipeline: the function VERTO should choose (profile-guided)
    note: str = ""            # pending cases


# --- plausible-but-wrong variants a tests-only tool would accept (Category C) ---

_UB_READ = """#include <vector>
#include <cstddef>
std::vector<int> build_histogram(std::size_t n){
  std::vector<int> out; out.reserve(n);
  for(std::size_t i=0;i<n;++i) out.emplace_back((int)(i*2));
  if(n>0){ volatile int s = out.data()[out.size()]; (void)s; }   // read one past end (UB)
  return out;
}"""

_UB_WRITE = """#include <vector>
#include <cstddef>
std::vector<int> build_histogram(std::size_t n){
  std::vector<int> out; out.reserve(n);
  for(std::size_t i=0;i<n;++i) out.emplace_back((int)(i*2));
  if(n>0){ out.data()[out.size()] = 0; }   // write one past end (UB)
  return out;
}"""

# Category D: memoized variant — correct and FASTER, but keeps a resident table,
# so peak memory regresses past budget. heavy() must match examples/memo_expensive.cpp.
_MEMO = """#include <vector>
#include <cstddef>
static int heavy(int x){ long s=0; for(int k=1;k<=64;++k) s+=(long)x*k%(k+7); return (int)(s&0x7fffffff); }
std::vector<int> transform_seq(std::size_t n){
    static std::vector<int> memo(500000,-1);
    std::vector<int> out; out.reserve(n);
    for(std::size_t i=0;i<n;++i){ int x=(int)(i%500000); if(memo[x]<0) memo[x]=heavy(x); out.push_back(memo[x]); }
    return out;
}"""


CASES: list[Case] = [
    # ---- Category A: structural / algorithmic change ----
    Case("A1-map-safe", "A structural", "pipeline", "accept",
         "Codeflash refuses data-structure swaps; a compiler can't change it",
         file=f"{EX}/map_safe.cpp"),
    Case("A1-map-ordered", "A structural", "pipeline", "reject",
         "the legality contract (order not observed) enforced by measurement",
         file=f"{EX}/map_ordered.cpp", reason="changed_output"),
    Case("A0-reserve", "A structural", "pipeline", "accept",
         "within-structure — weak wedge (both could), shown as a warm-up",
         file=f"{EX}/packet_stats.cpp"),

    # ---- Category C: safety (the crown jewel) ----
    Case("C1-oob-read", "C safety", "gate", "reject",
         "passes the differential test; ONLY a sanitizer catches it — a tests-only tool accepts it",
         file=f"{EX}/packet_stats.cpp", symbol="build_histogram", variant=_UB_READ,
         reason="unsafe"),
    Case("C2-oob-write", "C safety", "gate", "reject",
         "same: byte-identical output, heap-buffer-overflow write caught only by ASan",
         file=f"{EX}/packet_stats.cpp", symbol="build_histogram", variant=_UB_WRITE,
         reason="unsafe"),

    # ---- Controls: VERTO must NOT win ----
    Case("Ctrl-optimal", "Control", "pipeline", "none",
         "already optimal (unordered_map + reserved) — VERTO must claim NO win (no false positive)",
         file=f"{WD}/already_optimal.cpp"),

    # ---- Category B: profile-guided selection ----
    Case("B1-hotspot", "B profile", "pipeline", "accept",
         "profile-guided: optimizes hot_path (the true hotspot), not the first match — beats CompilerGPT (static-report-driven)",
         file=f"{EX}/multi_candidate.cpp", expect_symbol="hot_path"),

    # ---- Harness generation (verify-or-skip across signatures) ----
    Case("H1-new-signature", "Harness", "pipeline", "accept",
         "generates a harness from the REAL signature (vector→vector), not just f(size_t)",
         file=f"{EX}/squares_of.cpp", expect_symbol="squares_of"),
    Case("H2-skip-unsupported", "Harness", "pipeline", "none",
         "honestly SKIPS a custom-type / pointer signature it can't verify — no false positive",
         file=f"{WD}/unsupported.cpp"),
    Case("D1-mem-pareto", "D multi-obj", "gate", "reject",
         "faster (memoized, correct) but regresses peak memory past budget — a single-metric tool accepts it",
         file=f"{EX}/memo_expensive.cpp", symbol="transform_seq", variant=_MEMO,
         reason="peak_memory"),
]
