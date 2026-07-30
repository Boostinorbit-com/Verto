"""CLI output rendering — human, JSON, and codebase-scan formats, plus the exit
codes. Owns the color state (`--no-color` flips it via `set_color`)."""
from __future__ import annotations

import dataclasses
import json
import os

_COLOR = "NO_COLOR" not in os.environ   # verdict-render color; --no-color turns it off

# Reasons that mean "the proposer produced no usable change" — NOT a gate rejection of a real
# candidate. They're loop bookkeeping (e.g. an LLM re-asked after the win is already applied
# returns nothing to splice), so we hide them from the human view; the ledger + --json keep them.
_INTERNAL_REASONS = frozenset({"mutation_failed", "precondition_failed"})


def set_color(on: bool) -> None:
    global _COLOR
    _COLOR = on


def _col(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _speed(d) -> str:
    """A speed change in WORDS: "26.1% faster" / "26.1% slower".

    `p50_delta_pct` is positive for an improvement. The old render hardcoded a leading
    "-" and always coloured green, so a -26.1 REGRESSION printed as "--26.1%" in green
    and read like a win. Direction belongs in the text; colour only reinforces it.
    """
    if not d:
        return "n/a"
    return _col(f"{d:.1f}% faster", "32") if d > 0 else _col(f"{abs(d):.1f}% slower", "31")


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
    # Hide internal no-op rejects (the model had nothing more to add after the win) — they
    # read like errors but aren't. A real gate rejection ("not faster", correctness) stays.
    shown = [v for v in verdicts if v.accepted or v.reason not in _INTERNAL_REASONS]
    if not shown:
        if not quiet:
            print("  no verified opportunity found.")
        return
    for v in shown:
        if quiet and not v.accepted:
            continue
        name = v.candidate.transform.name if v.candidate else "?"
        mark = _col("ACCEPT", "32") if v.accepted else f"{_col('REJECT', '31')} ({v.reason})"
        cached = _col(" (cached)", "36") if getattr(v, "cached", False) else ""
        print(f"\n  {name}  →  {mark}{cached}")
        if quiet:
            if v.diff:
                print("\n" + _indent(_diff(v.diff)))
            continue
        if v.candidate:
            print(f"    rationale: {v.candidate.rationale}")
        if v.correctness:
            w = v.correctness.witness
            # build_ok FIRST: a build failure means the two never ran, so it can never
            # be "output differs" — reporting it that way blamed the rewrite for a
            # compile error in the ORIGINAL harness.
            if not w.build_ok:
                err = getattr(w, "build_error", "")
                detail = f"build failed — {err}" if err else "build failed"
            elif w.first_divergence:
                detail = f"output differs — {w.first_divergence}"
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
            print(f"    performance: p50 {v.performance.vector.get('p50')} ms "
                  f"({_speed(d)})  pareto={v.performance.pareto_pass}")
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


def _render_codebase(results: list, *, show_diff: bool = False) -> None:
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
                delta = f"  ({_speed(d)})" if d else ""
                tag = _col("✓ applied", "32") if v.applied else _col("ACCEPT", "32")
                n_applied += bool(v.applied)
                confirmed = _col("  ✓ tests", "32") if getattr(v, "tests_confirmed", False) else ""
                cached = _col("  (cached)", "36") if getattr(v, "cached", False) else ""
                print(f"    {tag}  {name} [{fn}]{delta}{confirmed}{cached}")
                if show_diff and v.diff:                 # --diff: show the change, in codebase mode too
                    print("\n" + _indent(_diff(v.diff), pad="      ") + "\n")
            elif v.reason.startswith("skipped"):        # gate couldn't verify (item #1/#4)
                n_skip += 1
                skip_reasons[v.reason] = skip_reasons.get(v.reason, 0) + 1
                print(f"    {_col('SKIP', '33')}    {name} [{fn}]  ({v.reason})")
            elif v.reason in _INTERNAL_REASONS:          # no usable change — not a gate reject
                continue
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


def _fail_on_exit(policy: str, *, accepted: bool) -> int:
    """#18 CI gate — remap the process exit code when `--fail-on` is set, so a run
    is pass/fail in a way CI can act on. (A real error returns 2 upstream and never
    reaches here.) The default codes (0=found) are backwards for a check — a repo
    with nothing to optimize would "fail" — which is exactly why this exists.
      'none' → always 0: findings are advisory; the build never fails on them.
      'any'  → 1 iff a verified optimization was found (a proven speedup to take)."""
    if policy == "any":
        return 1 if accepted else 0
    return 0        # 'none'
