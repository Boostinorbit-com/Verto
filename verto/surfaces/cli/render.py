"""CLI output rendering — human, JSON, and codebase-scan formats, plus the exit
codes. Owns the color state (`--no-color` flips it via `set_color`)."""
from __future__ import annotations

import dataclasses
import json
import os

_COLOR = "NO_COLOR" not in os.environ   # verdict-render color; --no-color turns it off


def set_color(on: bool) -> None:
    global _COLOR
    _COLOR = on


def _col(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _indent(text: str, pad: str = "    ") -> str:
    return "\n".join(pad + ln for ln in text.rstrip("\n").splitlines())


def _diff(text: str) -> str:
    """Git-style colored unified diff: green additions, red removals, dim hunk/file
    headers. Colored BEFORE indenting so the pad stays plain."""
    out = []
    for ln in text.rstrip("\n").splitlines():
        if ln.startswith(("+++", "---")):
            out.append(_col(ln, "1"))     # bold file headers
        elif ln.startswith("+"):
            out.append(_col(ln, "32"))    # addition — green
        elif ln.startswith("-"):
            out.append(_col(ln, "31"))    # removal — red
        elif ln.startswith("@@"):
            out.append(_col(ln, "36"))    # hunk header — cyan
        else:
            out.append(ln)                # context — default
    return "\n".join(out)


def _render_human(verdicts: list, *, quiet: bool = False, show_diff: bool = False,
                  applying: bool = False) -> None:
    if not verdicts:
        if not quiet:
            print("  no verified opportunity found.")
        return
    for v in verdicts:
        if quiet and not v.accepted:
            continue
        name = v.candidate.transform.name if v.candidate else "?"
        mark = _col("ACCEPT", "32") if v.accepted else f"{_col('REJECT', '31')} ({v.reason})"
        print(f"\n  {name}  →  {mark}")
        if quiet:
            if v.diff:
                print("\n" + _indent(_diff(v.diff)))
            continue
        if v.candidate:
            print(f"    rationale: {v.candidate.rationale}")
        if v.correctness:
            w = v.correctness.witness
            if w.first_divergence:
                detail = f"output differs — {w.first_divergence}"
            elif not w.build_ok:
                detail = "build failed"
            else:
                detail = w.sanitizer
            print(f"    correctness: Rung {v.correctness.rung} ({detail})")
            if getattr(v, "tests_confirmed", False):
                print(f"    {_col('✓ re-confirmed by the project’s own tests', '32')}")
            if w.sanitizer == "skipped(fast)" and v.accepted:
                print("    " + _col("⚠ UNSOUND (--fast): sanitizer skipped — "
                                    "diff-tested only, not memory-safety verified", "33"))
        if v.performance:
            d = v.performance.vector.get("p50_delta_pct")
            delta = _col("-%.1f%%" % d, "32") if d else "n/a"   # the win — green
            print(f"    performance: p50 {v.performance.vector.get('p50')} ms "
                  f"({delta})  pareto={v.performance.pareto_pass}")
        if v.accepted:
            if v.applied:
                print(f"    {_col('✓ applied to source', '32')}")
            elif applying:
                print(f"    {_col('⚠ not applied', '33')}: unsound (--fast) — re-run with --force")
            else:
                print("    (dry run — re-run with --apply to write this change)")
        if show_diff and v.diff:
            print("\n" + _indent(_diff(v.diff)))


def _render_json(verdicts: list) -> None:
    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return getattr(o, "name", str(o))       # render a Transform as its name
    print(json.dumps([enc(v) for v in verdicts], default=enc, indent=2))


def _render_codebase(results: list) -> None:
    n_files = n_cand = n_acc = n_applied = n_skip = 0
    skip_reasons: dict[str, int] = {}
    print(f"\n  codebase scan — {len(results)} translation unit(s)")
    for path, verdicts, err, skips in results:
        rel = os.path.relpath(path)
        if err:
            print(f"\n  {rel}\n    {_col('error', '31')}: {err}")
            continue
        if not verdicts and not skips:
            print(f"\n  {rel}\n    {_col('no opportunity found', '2')}")
            continue
        if verdicts:
            n_files += 1
        print(f"\n  {rel}")
        for v in verdicts:
            name = v.candidate.transform.name if v.candidate else "?"
            fn = getattr(v.candidate.transform, "target_func", None) if v.candidate else None
            if v.accepted:
                n_cand += 1
                n_acc += 1
                d = v.performance.vector.get("p50_delta_pct") if v.performance else None
                delta = _col(f"  (−{d:.1f}%)", "32") if d else ""   # the win — green
                tag = _col("✓ applied", "32") if v.applied else _col("ACCEPT", "32")
                n_applied += bool(v.applied)
                confirmed = _col("  ✓ tests", "32") if getattr(v, "tests_confirmed", False) else ""
                print(f"    {tag}  {name} [{fn}]{delta}{confirmed}")
            elif v.reason.startswith("skipped"):        # gate couldn't verify (item #1/#4)
                n_skip += 1
                skip_reasons[v.reason] = skip_reasons.get(v.reason, 0) + 1
                print(f"    {_col('SKIP', '33')}    {name} [{fn}]  ({v.reason})")
            else:
                n_cand += 1
                print(f"    {_col('REJECT', '31')}  {name} [{fn}]  ({v.reason})")
        for s in skips:                                  # sensor-level skips (item #4)
            n_skip += 1
            skip_reasons[s.reason] = skip_reasons.get(s.reason, 0) + 1
            print(f"    {_col('SKIP', '33')}    [{s.func}]  ({s.stage}: {s.reason})")
    print(f"\n  {'-' * 60}")
    tail = f" · {n_applied} applied" if n_applied else ""
    print(f"  {n_acc} accepted / {n_cand} candidate(s) across {n_files} file(s) "
          f"with opportunities · {n_skip} skipped{tail}")
    if skip_reasons:
        print(f"  {_col('skipped breakdown', '2')}:")
        for reason, count in sorted(skip_reasons.items(), key=lambda kv: -kv[1]):
            print(f"    {count:>3} × {reason}")


def _render_codebase_json(results: list) -> None:
    def enc(o):
        if dataclasses.is_dataclass(o):
            return dataclasses.asdict(o)
        return getattr(o, "name", str(o))
    payload = [{"file": f, "error": err, "verdicts": v, "skips": sk}
               for f, v, err, sk in results]
    print(json.dumps(payload, default=enc, indent=2))


def _codebase_exit(results: list) -> int:
    if any(v.accepted for _, vs, _, _ in results for v in vs):
        return 0
    if any(vs for _, vs, _, _ in results):
        return 3                       # candidates found but all rejected
    return 1                           # nothing found


def _exit_code(verdicts: list) -> int:
    if not verdicts:
        return 1
    if any(v.accepted for v in verdicts):
        return 0
    return 3
