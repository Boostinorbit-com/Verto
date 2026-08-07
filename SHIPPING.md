# BOOSTOPT GitHub Action — Shipping Checklist

Taking roadmap **#18** from *code-complete* to *proven on a real PR*. The Action is
built end-to-end (steps 1–4: `--fail-on` → entrypoint bridge → PR-comment poster →
Dockerfile + GHCR publish). Everything below is the part that **needs a real GitHub
repo + token** and therefore couldn't be verified on the dev machine.

Fill in your GitHub owner once and reuse it everywhere:

```
OWNER = <your github username or org>     # e.g. sir-nafis, or an org like "boostopt"
```

---

## Phase A — get the repo on GitHub (one-time)

The action image is built *from this repo*, so the repo must live on GitHub.

```bash
cd "AI_Optimizer_Network - (AION)"          # the repo root
gh repo create $OWNER/boostopt --source=. --private --push
# …or if a remote already exists:  git push
```

> ### ⚠ Gotcha 1 — the image ref must match your owner
> `examples/github-action/action.yml` has `runs.image: docker://ghcr.io/boostopt/action:v1`,
> and `.github/workflows/publish-action.yml` pushes to `ghcr.io/$OWNER/action`. These
> two strings **must be identical**. If `$OWNER` is not literally `boostopt`, edit
> `action.yml`'s `runs.image` to `docker://ghcr.io/$OWNER/action:v1` before publishing.

---

## Phase B — publish the action image

The publish workflow fires on a version tag:

```bash
git tag v0.1.0
git push --tags          # → runs .github/workflows/publish-action.yml
```

Then make the image public (GHCR packages are **private** on first push; a public
action needs a public image):

- GitHub → your profile/org → **Packages** → the **`action`** package →
  **Package settings** → **Change visibility → Public**.

Verify:

```bash
docker pull ghcr.io/$OWNER/action:v1
```

---

## Phase C — wire the Action into a repo that has PRs

Use either the same repo or a throwaway C++ repo.

> ### ⚠ Gotcha 2 — action.yml is in a subdirectory, not the repo root
> It lives at `examples/github-action/action.yml`, so the `uses:` reference is the
> **subdirectory form**:
> ```yaml
> uses: $OWNER/boostopt/examples/github-action@v0.1.0
> ```
> If you want the clean `uses: $OWNER/boostopt@v1`, add a thin `action.yml` at the repo
> root (identical `runs:` block) — then reference `$OWNER/boostopt@v0.1.0`.

Drop this into the C++ repo at `.github/workflows/boostopt.yml`:

```yaml
name: boostopt
on: pull_request

permissions:
  contents: read
  pull-requests: write        # ← Gotcha 3: the poster needs this to comment

jobs:
  boostopt:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0                   # full history so --changed can diff the PR

      - name: Generate compile_commands.json
        run: cmake -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

      - uses: $OWNER/boostopt/examples/github-action@v0.1.0
        with:
          compile-commands: build/compile_commands.json
          model: rules            # deterministic, no API key needed
          fail-on: none           # start advisory — comment only, never block
          github-token: ${{ github.token }}
```

> ### ⚠ Gotcha 3 — comment permissions
> Without `pull-requests: write`, the run still works but the poster silently
> no-ops (it's self-guarding). You'll see `skipping post …` in the logs.

---

## Phase D — trigger and watch

```bash
git checkout -b perf-demo
# add an un-reserved vector loop somewhere the build compiles, e.g.:
#   std::vector<int> f(std::size_t n){
#       std::vector<int> v;
#       for (std::size_t i=0;i<n;i++) v.push_back((int)i);
#       return v;
#   }
git commit -am "add a hot push_back loop"
git push -u origin perf-demo
gh pr create --fill
```

On the PR you should see, within a couple of minutes:
- a **boostopt** check in the checks list, and
- a **summary comment** with the verified `reserve()` suggestion and its trust triplet
  (why-safe / why-faster / measured).

---

## Recommended rollout (dial up trust over time)

| Stage | Inputs | Behaviour |
|---|---|---|
| 1. Advisory | `model: rules`, `fail-on: none` | Comments verified wins; never blocks. |
| 2. Gate | `fail-on: any` | Check goes **red** if a verified win is left unapplied. |
| 3. One-click | `mode: suggest` | Adds inline ` ```suggestion ` "Apply" buttons. |
| 4. Smarter proposer | `model: local` / `frontier` | LLM proposer (needs Ollama or an API key). |

Don't skip stage 1 — it's how the team learns the suggestions are real before any of
them can block a merge.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| No comment appears | Missing `pull-requests: write`, or not a `pull_request` event (Gotcha 3). |
| `uses:` can't find the action | Wrong path (Gotcha 2) or the tag/ref doesn't exist. |
| Image pull denied | Package still **private** (Phase B) or owner mismatch (Gotcha 1). |
| `no compile_commands.json` | The build step didn't emit it — check `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`. |
| Check green but nothing found | Genuinely nothing to optimize on the changed files, or the changed TUs aren't in the compile DB. |
| Suggestion not posted (in `suggest`) | GitHub only allows a suggestion on lines inside the PR's own diff — BOOSTOPT skips the rest and logs it. |

---

## What's intentionally NOT done yet (deferred)

- **`mode: pr`** (open a follow-up PR with the patches) — today it logs a notice and
  falls back to summary + inline suggestions.
- **`fail-on: regression`** (fail when the PR is *slower than a saved baseline*) —
  needs the baseline-diff feature; today the working prevent condition is `fail-on: any`.

---

*Concept reference: `Docs/BOOSTOPT_CI_Action.md` (·html). Interface: `examples/github-action/action.yml`.
Implementation: `entrypoint.py` · `comment.py` · `gh.py` · `Dockerfile`. Publish:
`.github/workflows/publish-action.yml`.*
