"""Repo-scale patch series (2C) — turn a whole-repo run into a reviewable deliverable.

Given the per-TU verdicts from `optimize_codebase` (or a single file's verdicts), write:
  - one numbered, `git apply -p1`-able `.patch` per accepted change, and
  - a `REPORT.md` ranking every verified win by measured speedup,
so the output is "here are N individually-verified speedups on your repo, as patches you
can review and apply" instead of a one-file-at-a-time console dump.

Each patch is verified in isolation by the gate; ranking is by measured p50 delta. The
consolidated ledger the engine already writes is the machine-readable companion.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class _Finding:
    file: str
    symbol: str
    transform: str
    delta_pct: float
    rung: int
    via: str
    udiff: str


def _collect(results) -> list[_Finding]:
    """Flatten (file, verdicts, …) tuples — or a bare verdict list — into ranked findings."""
    out: list[_Finding] = []
    for file, verdicts in _iter_files(results):
        for v in verdicts:
            if not (getattr(v, "accepted", False) and getattr(v, "udiff", "")):
                continue
            perf = getattr(v, "performance", None)
            delta = perf.vector.get("p50_delta_pct", 0.0) if perf else 0.0
            cand = getattr(v, "candidate", None)
            out.append(_Finding(
                file=file,
                symbol=getattr(cand.transform, "target_func", "") or "" if cand else "",
                transform=getattr(cand.transform, "name", "?") if cand else "?",
                delta_pct=float(delta), rung=getattr(v.correctness, "rung", 0) if v.correctness else 0,
                via=getattr(v, "via", "harness"), udiff=v.udiff))
    out.sort(key=lambda f: f.delta_pct, reverse=True)          # biggest measured win first
    return out


def _iter_files(results):
    """Accept both optimize_codebase results (tuples) and a single file's verdict list."""
    for r in results:
        if isinstance(r, tuple):
            yield r[0], r[1]
        else:                                                   # a bare Verdict (single-file mode)
            yield getattr(getattr(r, "candidate", None), "target_func", "") or "source", [r]
            return


def emit_patches(results, out_dir: str, *, single_file: str | None = None) -> tuple[int, str]:
    """Write the patch series + REPORT.md to `out_dir`. Returns (patch_count, report_path)."""
    if single_file is not None:
        findings = _collect([(single_file, results)])
    else:
        findings = _collect(results)
    os.makedirs(out_dir, exist_ok=True)

    for i, f in enumerate(findings, 1):
        stem = f"{i:04d}-{f.transform}-{os.path.basename(f.file).replace('.', '_')}"
        with open(os.path.join(out_dir, stem + ".patch"), "w", encoding="utf-8") as fh:
            fh.write(f.udiff)

    report = os.path.join(out_dir, "REPORT.md")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write("# BOOSTOPT — verified optimizations\n\n")
        if not findings:
            fh.write("No verified wins in this run.\n")
        else:
            fh.write(f"{len(findings)} verified win(s), ranked by measured speedup. "
                     "Each `.patch` is independently gate-verified — apply with "
                     "`git apply -p1 <file>`.\n\n")
            fh.write("| # | speedup | transform | function | file | correctness |\n")
            fh.write("|---|--------:|-----------|----------|------|-------------|\n")
            for i, f in enumerate(findings, 1):
                basis = "project tests" if f.via == "tests" else f"Rung {f.rung} (sanitizers)"
                fh.write(f"| {i} | {f.delta_pct:+.1f}% | `{f.transform}` | `{f.symbol}` | "
                         f"`{f.file}` | {basis} |\n")
    return len(findings), report
