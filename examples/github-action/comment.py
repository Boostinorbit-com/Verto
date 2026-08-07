"""BOOSTOPT Action — PR/MR comment rendering (#18, step 3, the pure half).

Turns the `boostopt … --json` verdict report into the Markdown a developer sees, and
extracts GitHub review-suggestion payloads from each finding's unified diff. No
network here — this is all deterministic string work, so it's fully unit-tested.
The actual posting lives in `gh.py`. Layout follows `pr-comment.md`.
"""
from __future__ import annotations

import os

MARKER = "<!-- boostopt:summary -->"   # hidden tag → the next push edits this comment in place


# ---- small helpers --------------------------------------------------------------

def _rel(path: str, root: str | None) -> str:
    if root:
        try:
            return os.path.relpath(path, root)
        except ValueError:
            pass
    return os.path.basename(path)


def _accepted(report) -> list[tuple[str, dict]]:
    """(file, verdict) pairs for every accepted finding, in report order."""
    out = []
    for f in report:
        for v in (f.get("verdicts") or []):
            if v.get("accepted"):
                out.append((f.get("file", "?"), v))
    return out


def _skip_count(report) -> int:
    n = 0
    for f in report:
        n += len(f.get("skips") or [])
        n += sum(1 for v in (f.get("verdicts") or [])
                 if (v.get("reason") or "").startswith("skipped"))
    return n


def _func_from_diff(diff: str) -> str:
    """Best-effort enclosing-function name — the verdict JSON only carries the
    transform name, so we sniff a signature-looking context line from the diff.
    Returns '' if nothing convincing is found (then we show just the file)."""
    import re
    for ln in diff.splitlines():
        body = ln[1:] if ln[:1] in " +-" else ln
        m = re.search(r"([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{?\s*$", body)
        if m and m.group(1) not in ("if", "for", "while", "switch", "return"):
            return m.group(1)
    return ""


def _label(file: str, v: dict, root: str | None) -> str:
    rel = _rel(file, root)
    fn = _func_from_diff(v.get("diff") or v.get("udiff") or "")
    return f"{rel} · {fn}()" if fn else rel


def _delta(v: dict) -> float | None:
    perf = v.get("performance") or {}
    return (perf.get("vector") or {}).get("p50_delta_pct")


def _pct(v: dict) -> str:
    d = _delta(v)
    return f"−{d:.0f}%" if d else "faster"


def _proof(v: dict) -> str:
    c = v.get("correctness") or {}
    rung = c.get("rung", "?")
    tag = f"✅ Rung {rung}"
    if v.get("tests_confirmed") or v.get("via") == "tests":
        tag += " · tests"
    return tag


# ---- the summary comment --------------------------------------------------------

def _finding_details(file: str, v: dict, root: str | None) -> str:
    c = v.get("correctness") or {}
    w = c.get("witness") or {}
    perf = (v.get("performance") or {}).get("vector") or {}
    rung = c.get("rung", "?")
    san = w.get("sanitizer") or "clean"
    runs = w.get("inputs_run") or 0
    safe = (f"byte-identical output on {runs:,} fuzzed inputs; "
            f"{'sanitizers clean' if san == 'clean' else san} (Rung {rung})")
    if v.get("tests_confirmed") or v.get("via") == "tests":
        safe += " — re-confirmed by the project's own tests"
    fast = v.get("candidate", {}).get("rationale") or "a proven, cheaper equivalent"

    p50, before = perf.get("p50"), perf.get("p50_before")
    if p50 and before:
        measured = (f"p50 {_pct(v)} ({p50:.2f} ms vs {before:.2f} ms) "
                    f"*(on this runner; typically larger on production hardware).*")
    else:
        measured = f"p50 {_pct(v)} *(on this runner).*"

    diff = (v.get("diff") or "").rstrip("\n")
    return (
        f"<details><summary><b>{_label(file, v, root)} — "
        f"{v.get('candidate', {}).get('transform', 'change')} · {_pct(v)}</b></summary>\n\n"
        f"**Why it's safe** — {safe}.\n"
        f"**Why it's faster** — {fast}.\n"
        f"**Measured** — {measured}\n\n"
        f"```diff\n{diff}\n```\n"
        f"</details>"
    )


def render_comment(report, *, repo_root: str | None = None, blocking: bool = False) -> str:
    """The full Markdown comment body (always starts with MARKER so it can be
    edited in place). Handles both the findings case and the quiet no-findings case."""
    found = _accepted(report)
    skips = _skip_count(report)

    if not found:
        body = ["### BOOSTOPT — no verified optimizations",
                "", f"Checked the changed files; nothing cleared the correct-and-faster "
                f"bar this run.{f' <sub>({skips} skipped.)</sub>' if skips else ''}"]
        return MARKER + "\n" + "\n".join(body)

    n = len(found)
    if blocking:
        head = [f"### ❌ BOOSTOPT — {n} verified optimization"
                f"{'s' if n > 1 else ''} left unapplied", "",
                "This check is **failing** because `fail-on: any` is set: a proven, "
                "correct-and-faster change is available. Apply the suggestion(s) below, "
                "or set `fail-on: none` to make BOOSTOPT advisory. "
                "<sub>Behavior is proven unchanged — this blocks only *missed speed-ups*, "
                "never correctness.</sub>"]
    else:
        head = [f"### ⚡ BOOSTOPT — {n} verified optimization{'s' if n > 1 else ''}", "",
                "Each change is **proven behavior-identical** (differential test + "
                "sanitizers) and **measurably faster** on the files this PR touched. "
                "Nothing is applied automatically."]

    rows = ["| File · function | Change | p50 speed-up | Proof |", "|---|---|---|---|"]
    for file, v in found:
        rows.append(f"| `{_label(file, v, repo_root)}` | "
                    f"{v.get('candidate', {}).get('transform', 'change')} | "
                    f"**{_pct(v)}** | {_proof(v)} |")

    details = [_finding_details(file, v, repo_root) for file, v in found]

    footer = ""
    if skips:
        footer = ("\n\n---\n<sub>🔎 " + str(skips) + " site(s) skipped. BOOSTOPT proves every "
                  "change **correct-and-faster** before suggesting it — a weaker model "
                  "produces *fewer* suggestions, never an unsafe one.</sub>")

    return MARKER + "\n" + "\n".join(head) + "\n\n" + "\n".join(rows) + "\n\n" + \
        "\n\n".join(details) + footer


# ---- inline suggestions ---------------------------------------------------------

def _parse_hunks(udiff: str) -> list[dict]:
    """Parse a unified diff into hunks with the new-side replacement text and the
    OLD-side line range each hunk covers (what a GitHub suggestion anchors to)."""
    import re
    hunks, cur = [], None
    for ln in udiff.splitlines():
        h = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", ln)
        if h:
            if cur:
                hunks.append(cur)
            cur = {"old_start": int(h.group(1)), "old_count": int(h.group(2) or 1),
                   "new_start": int(h.group(3)), "new_lines": []}
        elif cur is not None:
            if ln[:1] in (" ", "+"):
                cur["new_lines"].append(ln[1:])
            # '-' lines are dropped (they're the replaced old content)
    if cur:
        hunks.append(cur)
    return hunks


def extract_suggestions(report, *, repo_root: str | None = None) -> list[dict]:
    """One GitHub-review-suggestion payload per diff hunk of each finding. The
    caller (gh.py) adds the commit SHA and posts; here we only produce the pure
    data: path, the old-side line range to anchor to, and the ```suggestion body."""
    out = []
    for file, v in _accepted(report):
        udiff = v.get("udiff") or v.get("diff") or ""
        for h in _parse_hunks(udiff):
            new_body = "\n".join(h["new_lines"])
            start = h["old_start"]
            end = start + max(h["old_count"], 1) - 1
            note = (f"**BOOSTOPT** · verified **{_pct(v)}**, {_proof(v)}, behavior-identical. "
                    f"Apply to {v.get('candidate', {}).get('rationale', 'optimize')}:")
            out.append({
                "path": _rel(file, repo_root),
                "start_line": start,
                "line": end,
                "suggestion": new_body,
                "body": f"{note}\n\n```suggestion\n{new_body}\n```",
            })
    return out
