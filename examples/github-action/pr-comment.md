# VERTO — the PR / MR comment layout

This is the *design* surface of the Action: the comment a developer actually sees. It's plain **Markdown** (both GitHub PR comments and GitLab MR notes render it), so this file doubles as the spec *and* previews roughly how it looks.

> **Implemented (#18 step 3).** This layout is now produced by real code: [`comment.py`](comment.py) renders the summary + suggestions (pure, unit-tested), and [`gh.py`](gh.py) posts them to GitHub (`urllib`-only, self-guarding). This file remains the human-readable spec.

**Design goals**, in priority order:
1. **Trust first.** VERTO's whole pitch is *verified* — lead with the proof (behavior-identical + sanitizers), not just a number.
2. **Scannable in 3 seconds.** A summary table up top; details collapsed.
3. **Honest about the number.** The speed-up is measured on the runner (toolchain-dependent) — say so.
4. **Low-noise.** One comment per PR, *updated* on each push (never a new comment each time). Skips are disclosed but quiet.

---

## 1. The summary comment (posted once, updated on each push)

> ### ⚡ VERTO — 2 verified optimizations
>
> Both changes are **proven behavior-identical** (differential test + ASan / UBSan / TSan) and **measurably faster** on the files this PR touched. Nothing is applied automatically.
>
> | File · function | Change | p50 speed-up | Proof |
> |---|---|---|---|
> | `route.cpp` · `route_costs()` | `reserve()` before the loop | **−53%** | ✅ Rung 3 |
> | `report.cpp` · `scaled_series()` | `reserve()` before the loop | **−49%** | ✅ Rung 3 |
>
> <details><summary><b>route.cpp · route_costs() — reserve() · −53%</b></summary>
>
> **Why it's safe** — byte-identical output on 1,000 fuzzed inputs; ASan + UBSan + TSan clean (Rung 3).
> **Why it's faster** — avoids ~11 vector reallocations; a win the compiler can't make (it can't prove the final size).
> **Measured** — p50 −53% · p99 −41% · peak-memory ±0% *(on this runner; typically larger on production hardware).*
>
> ```diff
>  std::vector<int> route_costs(std::size_t n) {
>      std::vector<int> out;
> +    out.reserve(n);
>      for (std::size_t i = 0; i < n; ++i)
> -        out.push_back(point_weight(i) + (int)i);
> +        out.emplace_back(point_weight(i) + (int)i);
>      return out;
>  }
> ```
> </details>
>
> <details><summary><b>report.cpp · scaled_series() — reserve() · −49%</b></summary>
>
> **Why it's safe** — byte-identical on 1,000 fuzzed inputs; Rung 3 clean.
> **Why it's faster** — removes the reallocation cascade on a `std::vector` grown in a loop.
> **Measured** — p50 −49% · p99 −38% · peak-memory ±0% *(this runner).*
>
> ```diff
>      std::vector<double> out;
> +    out.reserve(n);
> ```
> </details>
>
> ---
> <sub>🔎 2 functions skipped (couldn't synthesize inputs). VERTO proves every change **correct-and-faster** before suggesting it — a weak model produces *fewer* suggestions, never an unsafe one. Tune in `.verto.toml`.</sub>

**Notes**
- The header count and the table are the 3-second read. Everything heavy is behind `<details>` so the comment stays short.
- "Why it's safe / Why it's faster / Measured" is the trust triplet — the correctness lines are stated as facts (toolchain-independent); the speed-up carries the *"this runner"* caveat.
- The footer discloses **skips** honestly and reminds the reader the gate is real.

---

## 2. Inline suggestion (`mode: suggest`) — one per finding, anchored to the lines

Posted as a review comment on the changed lines, so the reviewer gets an **Apply** button:

> **VERTO** · verified **−53%**, Rung 3, behavior-identical. Apply to pre-size the vector:
>
> ````
> ```suggestion
>     std::vector<int> out;
>     out.reserve(n);
> ```
> ````

- **GitHub** suggestion syntax: a fenced ` ```suggestion ` block → renders an "Apply suggestion" / "Add to batch" button.
- **GitLab** suggestion syntax: ` ```suggestion:-0+0 ` (the `-0+0` = how many lines above/below it replaces) → an "Apply suggestion" button on the MR.
- In `suggest` mode you post these *plus* the §1 summary (so there's still one scannable overview).

---

## 3. No-findings (keep it quiet)

Don't spam a big comment when there's nothing to suggest. Either update the existing comment to a one-liner, or post nothing and just set a neutral check status:

> ### VERTO — no verified optimizations
> Checked 3 changed files; nothing cleared the correct-and-faster bar this run. <sub>(2 skipped — couldn't synthesize inputs.)</sub>

*(Recommended: collapse or minimize this so a clean PR isn't cluttered.)*

---

## 4. Prevent mode (`fail-on: any`) — a blocked merge *(shipped)*

Same findings as §1, but the check goes **red**: there's a verified, correct-and-faster change on the table and the PR hasn't taken it. The comment stays identical — only the check status and the closing line change:

> ### ❌ VERTO — 2 verified optimizations left unapplied
>
> *(the same summary table + suggestion folds as §1)*
>
> This check is failing because **`fail-on: any`** is set: a proven correct-and-faster change is available. Apply the suggestion(s) above, or lower the gate to `fail-on: none` to make this advisory. <sub>Behavior is proven unchanged — this blocks only *missed speed-ups*, never correctness.</sub>

*Prevent is `fail-on: any` today. A **planned** `fail-on: regression` variant will instead fail when the PR is slower than a saved baseline — a "guard against losses" gate that needs the baseline-diff feature (roadmap). Sketch of that future comment:*

> ### ❌ VERTO — performance regression *(planned — needs baselines)*
>
> `parse.cpp · tokenize()` is **+18% slower** (p50) than the baseline on `main`. Behavior is unchanged (differential test passed) — purely a speed regression.

---

## Mechanics the implementer needs

- **One comment, updated in place.** Tag the comment with a hidden marker (e.g. `<!-- verto:summary -->`) so the next push *edits* it instead of adding a new one. Inline suggestions are re-posted only for lines that still apply.
- **Everything comes from `--json`.** The Action runs `verto optimize --changed … --json`, then this layout is pure rendering of that payload — identical logic for GitHub and GitLab; only the *post* call and the suggestion fence differ.
- **Diffs** use ` ```diff ` (universal). **Suggestions** use the platform fence above.
- **Tone:** state correctness as fact, speed-up with the runner caveat. Never oversell the number — the proof is the product.
