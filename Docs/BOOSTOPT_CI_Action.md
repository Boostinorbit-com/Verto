# BOOSTOPT in Your CI — the GitHub Action, explained from scratch

**This document explains roadmap item #18: the BOOSTOPT GitHub Action — the thing a C++ team installs so that, on every code change, BOOSTOPT automatically finds verified speed-ups and shows them right in the pull request.** It assumes no prior knowledge: every term is defined the first time it appears.

---

## 1. Who this is for, and the one confusion to clear first

There are **two completely different things** in BOOSTOPT's plan that both contain the words "CI". Do not mix them up:

| | **BOOSTOPT's own CI** (#15, already built) | **The BOOSTOPT Action** (#18, this doc) |
|---|---|---|
| Whose project it runs in | The **BOOSTOPT repository** | **Your** C++ project |
| What it does | Tests that BOOSTOPT itself isn't broken | Runs BOOSTOPT **on your code** and suggests optimizations |
| Who benefits | BOOSTOPT's developers | **You and your team** |

This document is only about the second one — **the Action you would add to your own project.**

---

## 2. The idea in one picture

```
   You open a Pull Request (a proposed code change)
            │
            ▼
   GitHub runs the BOOSTOPT Action automatically
            │
            ▼
   BOOSTOPT looks only at the files you changed, and for each one:
     · compiles it            (does it still build?)
     · runs it on test inputs (does it produce identical output? → CORRECT)
     · runs sanitizers        (any hidden memory/threading bugs?)
     · benchmarks it          (is the optimization actually faster?)
            │
            ▼
   BOOSTOPT writes a comment on your Pull Request:
     "Found 2 verified optimizations — here are the diffs. Click to apply."
```

You never leave GitHub. You never run anything by hand. BOOSTOPT does the work and *proves* each suggestion before showing it to you.

---

## 3. The words you need (each defined once)

- **CI / CD** — "Continuous Integration / Continuous Delivery." In plain terms: **automation that runs every time you change code** — building it, testing it, checking it. GitHub runs these automations for you.
- **Pull Request (PR)** — a *proposed* change to a codebase, opened for review before it's merged in. It's where teammates comment, and where automated checks report. This is where BOOSTOPT puts its findings.
- **GitHub Action** — a **reusable piece of automation** you plug into a project. You add a small file and, from then on, GitHub runs that automation on the events you choose (e.g. "on every PR"). The BOOSTOPT Action is one of these.
- **Workflow** — the small YAML file (in `.github/workflows/`) where you say *when* to run an Action and *with what settings*. You write ~10 lines once.
- **Runner** — the **temporary computer GitHub rents to run your automation**. It's a fresh, shared virtual machine that exists for a few minutes, then disappears. (This detail matters later — see §7.)
- **`compile_commands.json`** — a file that lists **exactly how each of your C++ files is compiled** (which flags, include paths, defines). Real C++ can't be compiled without this information, so BOOSTOPT needs it. Most build systems can generate it automatically (CMake does it with one flag).
- **"Only the changed files" (`--changed`)** — instead of scanning your whole project every time (slow), BOOSTOPT looks **only at the files this PR touched.** Fast, and relevant.
- **A "verified finding"** — an optimization BOOSTOPT has **proven** is (a) behavior-identical and (b) faster. BOOSTOPT never shows you an unproven guess.
- **A GitHub "suggested change"** — a special kind of PR comment that contains a diff **you can apply with one click** in the review screen. BOOSTOPT can post its fixes this way.

---

## 4. What the Action actually does, step by step

When a PR is opened or updated, the Action runs these steps on the runner:

1. **Check out your code** at the PR's version.
2. **Figure out which files changed** in this PR (compared to the base branch).
3. **Get the compilation info** — read your `compile_commands.json` (or run your build command to generate it).
4. **Run BOOSTOPT on just those files** — `boostopt optimize --changed <base> -p compile_commands.json`. For each candidate optimization, the trusted gate compiles it, differential-tests it, runs sanitizers, and benchmarks it.
5. **Collect the verified findings** as machine-readable JSON.
6. **Report back on the PR** — a comment listing each proven optimization with its diff (and, optionally, one-click "suggested changes").

Everything above is a thin wrapper over the same BOOSTOPT engine the command-line tool already uses — the Action just *triggers* it and *renders* the result into GitHub.

---

## 5. The four ways it can behave — and yes, you can combine them

These four aren't a rigid "pick exactly one." They're really **two independent dials**, so you can run several at once. (My earlier "start with Comment + Suggested changes" was a *rollout order*, not a limit.)

**Dial A — how found *wins* are delivered** (choose one — they're three intensities of the *same* thing):

1. **Comment (safest, the default)** — a PR note: *"2 verified optimizations found"* with the diffs. Changes nothing; you decide.
2. **Suggested changes** — the same findings as **one-click-apply** suggestions in the review UI. A linter that also *fixes* — except every fix is proven correct-and-faster.
3. **Auto-PR** — a *separate* follow-up pull request with the applied, verified patches, for you to review and merge.

**Dial B — do you also *block the merge*?** (independent on/off, stacks on top of any delivery choice):

4. **Prevent mode** — **fail the check when BOOSTOPT found a verified win you didn't take** (`fail-on: any`). Turns the comment from advice into a gate: *"there's a proven, correct-and-faster change here — don't merge past it."* **Shipped.**
   - *Planned variant — `fail-on: regression`:* fail when your PR is *slower than a saved baseline*. This is the "guard against losses" flavor; it needs the baseline-diff feature (roadmap), so today the working prevent condition is `any`.

Because they're separate dials, **you can have them together** — e.g. **Suggested changes + Prevent**: suggest every proven win inline *and* fail the check until one is taken. The only genuine either/or is the *delivery style* (comment vs suggest vs auto-PR — three ways to present the same wins).

In the interface (§8) that's the `mode` input (`comment` | `suggest` | `pr`) plus `fail-on: any` for Prevent — set both, and you get both.

**Recommended rollout:** start with **Comment** → graduate to **Suggested changes** → turn on **Prevent** (`fail-on: any`) once the team trusts the findings. Reach for **Auto-PR** whenever a separate PR suits your flow better than inline suggestions.

*What the comment actually looks like* (summary comment, inline suggestion, prevent-mode failure) is drafted in [`examples/github-action/pr-comment.md`](../examples/github-action/pr-comment.md) — it renders on GitHub, so it previews the design.

---

## 6. How it's delivered (a "Docker action")

BOOSTOPT needs a C++ toolchain (`clang++` with sanitizers) to do its job. Rather than make every user install that, the Action ships as a **Docker action**: a pre-built container image that already contains clang, the sanitizers, and BOOSTOPT. GitHub pulls the image and runs it. The user installs *nothing* — they just add the workflow file.

(BOOSTOPT already has the `Dockerfile` for this; the Action is a thin `action.yml` on top of it.)

### CI portability — works on GitLab too (and any CI)

Because BOOSTOPT is really just **a CLI in a Docker image**, it runs on *any* CI — GitHub, GitLab, Jenkins, CircleCI. The engine and every "entry" are universal; only a thin *wrapper* per platform differs:

```
        one engine  (boostopt CLI + Docker)  ← universal; every input maps to a CLI flag
         ├── GitHub Action     (action.yml + PR comments)   ← GitHub wrapper
         └── GitLab Component  (spec:inputs + MR notes)      ← GitLab wrapper
```

**GitLab** has its own analog of the Action's inputs — a **CI/CD Component** with a `spec: inputs:` block. The *entries are the same* (they map to the same `boostopt` flags); only two things differ syntactically:

| | GitHub Actions | GitLab CI/CD |
|---|---|---|
| Input names | `compile-commands` (hyphens) | `compile_commands` (underscores) |
| Reading a value | `${{ inputs.x }}` / `with:` | `$[[ inputs.x ]]` |
| Review UI it posts to | Pull Request comment | **Merge Request** note (different API) |

The only genuinely per-platform work is **posting the result** — GitHub's PR-comment API vs GitLab's MR-note API — both fed by the same `--json` output. Everything upstream (find + verify) is identical.

Runnable samples for both live in [`examples/`](../examples/): [`github-action/`](../examples/github-action/) (workflow + `action.yml`) and [`gitlab-ci/`](../examples/gitlab-ci/) (a plain `.gitlab-ci.yml` job **and** a CI/CD Component with matching `inputs:`).

---

## 7. The one genuinely hard part — explained simply

Here is the honest challenge, and it's worth understanding because it shapes everything.

**A "runner" is a shared, rented computer, and shared computers are *noisy*** — other people's jobs are running on the same hardware, the CPU speed fluctuates, and timing measurements bounce around. BOOSTOPT's whole promise is *"correct AND faster,"* and *"faster"* is measured by timing. On a noisy runner, a change that's genuinely **30% faster on your laptop can measure as barely 1% faster on the runner** — and BOOSTOPT, being honest, would then say *"not faster, no finding."*

So the naive version of the Action would *under-report* real wins on noisy hardware and look weak.

**The key realization (learned the hard way building #15):** the two halves of BOOSTOPT's guarantee behave very differently on shared hardware —

- **Correctness is rock-solid regardless of hardware.** A memory bug is a memory bug on any machine; "the output is byte-identical" is true on any machine. The sanitizer + differential-test half of the gate is **toolchain-independent** and always trustworthy.
- **The exact speed-up number is hardware-dependent.** How big the win *measures* depends on the specific CPU and compiler on that runner.

So the Action's design answer is to **separate what it proves from what it merely measures**:

- Report the **proven** part with full confidence: *"This change is behavior-identical (differential test + sanitizers) and removes N reallocations — a structural win the compiler cannot make."*
- Report the **measured** speed-up with an honest caveat: *"measured ~X% faster on this runner; typically larger on production hardware,"* and use extra measurement repetitions to steady it.

The upshot: on CI, BOOSTOPT's unique, durable value is the **correctness proof and the non-obvious optimization** — the exact percentage is secondary. That's actually a *stronger* and more honest pitch than a fragile hard number.

---

## 8. Setting it up for a team (what you'd actually write)

Three things:

**1. Make your build emit `compile_commands.json`.** With CMake, that's one flag:
```
cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

**2. Add a workflow file** — `.github/workflows/boostopt.yml` (sketch):
```yaml
name: BOOSTOPT
on: pull_request
jobs:
  optimize:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }        # so BOOSTOPT can see the diff vs the base branch
      - run: cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
      - uses: boostopt/action@v1            # ← the BOOSTOPT Action
        with:
          compile-commands: build/compile_commands.json
          mode: comment                  # comment | suggest | pr
```

**3. (Optional) A `.boostopt.toml`** in your repo root sets team defaults once — which model, minimum speed-up, budget — and every run follows it.

That's the entire user-facing setup: one build flag, one short workflow file, one optional config.

### The full interface — every input, output, and secret

An Action is defined by an **`action.yml`** file, which declares the **inputs** a user may pass (the `with:` keys), the **outputs** later steps can read, and how it runs. Here is the proposed contract — each input maps to a BOOSTOPT CLI flag that already exists, so this is a real spec, not a wish.

**Inputs** (set under `with:`):

| Input | What it controls | Default | CLI flag it maps to |
|---|---|---|---|
| `compile-commands` | path to `compile_commands.json` (or a build dir holding one) | auto-detect | `-p` |
| `build-command` | a shell command run first to *generate* the DB (e.g. a `cmake` line) | — | (pre-step) |
| `base-ref` | the branch to diff against — decides which files count as "changed" | the PR's base branch | `--changed` |
| `mode` | how found *wins* are delivered: `comment` · `suggest` · `pr` | `comment` | (delivery) |
| `model` | proposer: `rules` (deterministic, no key) · `local` · `frontier` | `rules` | `--model` / `--offline` |
| `min-speedup` | reject wins smaller than this percent | `2` | `--min-speedup` |
| `min-rung` | correctness rung to require (`1` = diff test, `3` = sanitizers) | `3` | `--min-rung` |
| `objectives` | performance dimensions to gate on | `p50,p99,peak_memory` | `--objectives` |
| `include` / `exclude` | globs to narrow which changed files are considered | — | (path scoping) |
| `jobs` | translation units to verify in parallel | auto | `--jobs` |
| `budget` | LLM spend cap — tokens (`500k`), money (`$2`), or time (`90s`) | — | `--budget` |
| `llm-url` / `llm-model` | hosted-model endpoint + name (for `model: frontier`) | — | `--llm-url` / `--llm-model` |
| `fail-on` | make the check red on: `none` · `any` (verified win left unapplied). `regression` (vs baseline) planned | `none` | `--fail-on` |
| `config-file` | path to the team's `.boostopt.toml` | `.boostopt.toml` | `--config-file` |
| `metamorphic` | also run the opt-in metamorphic rung | `false` | `--metamorphic` |
| `github-token` | token used to post the PR comment / suggestions | `${{ github.token }}` | (GitHub API) |
| `api-key` | hosted-model key — pass a **secret**, never a literal | — | env `OPENAI_API_KEY` |
| `boostopt-token` | account token for BOOSTOPT's **hosted** services (managed model / clean-room bench) — pass a **secret**. NOT a local unlock; the self-run Action is free | — | (server-side entitlement) |
| `extra-args` | raw passthrough to the `boostopt` CLI (escape hatch) | — | (any flag) |

**Outputs** (read by later steps as `${{ steps.boostopt.outputs.<name> }}`):

| Output | Meaning |
|---|---|
| `status` | `clean` (nothing to do) · `found` (verified wins) · `regressed` (prevent-mode failure) |
| `findings` | number of verified optimizations |
| `applied` | number applied / posted as suggestions |
| `regressions` | number of regressions caught (prevent mode) |
| `report-json` | path to the full machine-readable verdict report |
| `patches` | path to the emitted `git apply`-able patch series |

**Secrets** (passed via `with:` from `${{ secrets.* }}`, never hard-coded): `github-token` (to comment), the model `api-key` (your own key, only if `model: frontier`), and `boostopt-token` (only when using BOOSTOPT's hosted services — the free self-run Action needs none).

**The `action.yml` itself** (the interface definition — sketch):
```yaml
name: "BOOSTOPT"
description: "Verified C++ optimizations on your pull requests."
branding: { icon: "zap", color: "blue" }
inputs:
  compile-commands: { description: "path to compile_commands.json or a build dir", required: false, default: "" }
  mode:             { description: "comment | suggest | pr", required: false, default: "comment" }
  model:            { description: "rules | local | frontier", required: false, default: "rules" }
  min-speedup:      { description: "reject wins below this %", required: false, default: "2" }
  base-ref:         { description: "branch to diff against", required: false, default: "" }
  github-token:     { description: "token to post PR comments", required: false, default: "${{ github.token }}" }
  api-key:          { description: "hosted-model key (secret)", required: false, default: "" }
  boostopt-token:      { description: "hosted-services account token (secret); free self-run needs none", required: false, default: "" }
  # …the rest of the inputs above…
outputs:
  status:      { description: "clean | found | regressed" }
  findings:    { description: "number of verified optimizations" }
  report-json: { description: "path to the full JSON report" }
runs:
  using: "docker"            # reuses BOOSTOPT's Dockerfile / a published image
  image: "docker://ghcr.io/boostopt/action:v1"
  # the entrypoint reads inputs from INPUT_* env vars, runs `boostopt`, posts results
```

A user's workflow then references it declaratively — the fuller form of the sketch above:
```yaml
      - id: boostopt
        uses: boostopt/action@v1
        with:
          compile-commands: build/compile_commands.json
          mode: suggest
          model: rules
          min-speedup: "3"
          fail-on: any               # block the merge if a verified win is left unapplied
          # api-key: ${{ secrets.OPENAI_API_KEY }}   # only if model: frontier
      - run: echo "BOOSTOPT found ${{ steps.boostopt.outputs.findings }} optimizations"
```

**Copy-pasteable sample files** live in [`examples/github-action/`](../examples/github-action/): a fully-commented **`boostopt.yml`** (the workflow you drop into your repo) and the **`action.yml`** (this interface definition, as a real file).

---

## 9. Free vs paid — why this is the "commercial" item

A GitHub Action is just YAML that runs on *your* runners, so the Action itself can't be "the paid thing." Instead, the money rides on **what powers it**:

- **Free:** the open-source tool + the **self-run Action** — deterministic rules or a **local** model, running on *your* CI, fully correctness-verified. No token, no account.
- **Paid:** things that run on **BOOSTOPT's servers**, so they authenticate to a hosted account (via `boostopt-token`): a **managed stronger model**, **clean-room benchmarking** (trustworthy numbers a noisy runner can't give), a **team dashboard** (cross-repo trends), the **cross-project pattern learning**, and support.

The paywall is **architectural, not a client-side flag** — free things run on your machine/CI; paid things run on BOOSTOPT's, where entitlement is checked **server-side**. And the verification gate is identical at every tier — a better model only changes *how many* good suggestions appear, never whether a bad one could slip through.

---

## 10. What exists today, and what's left to build

**#18 is not built yet** — it's a Phase-5 (commercial) item. But most of the hard machinery already exists from earlier work, so it's largely *assembly*:

| Already built | Used by #18 for |
|---|---|
| The verification engine + gate | the actual proving |
| `Dockerfile` | the Docker action's image |
| `--changed` + `--jobs` | scoping to the PR's files, in parallel |
| `--json` output | building the PR comment |
| `--emit-patches` | the ranked diffs / suggestions |
| `.boostopt.toml` | the team's config |
| budget cap | bounding LLM cost per PR |
| benchmark robustness (from #15) | surviving noisy runners |

**Left to build:** the `action.yml` wrapper, the PR-comment / suggested-changes integration, the free/paid gating, and (later) prevent-mode + the dashboard.

---

## 11. Quick answers to the obvious questions

- **Does it change my code without asking?** No — the default only *comments*. Anything applied is either your one click ("suggested changes") or a separate PR you review.
- **Is my code uploaded anywhere?** With the local/rules model, no — it runs entirely on your runner. Only if you opt into a hosted model does the relevant code go to that endpoint (your choice, your key/endpoint).
- **What if a suggestion is wrong?** It can't be silently wrong — every suggestion passed the correctness gate (identical behavior + clean sanitizers). A weak model just produces *fewer* suggestions, never an unsafe one.
- **Will it slow my CI down?** It only looks at changed files, caches compiled artifacts, and you can bound its time/cost. It's designed to be scoped, not to re-scan everything.
- **Which build systems work?** Anything that can produce a `compile_commands.json` — CMake (built-in), or tools like Bear for Make/others.
- **Is this the same as BOOSTOPT's own CI?** No — see §1. That one tests BOOSTOPT; this one runs BOOSTOPT on *your* code.

---

*Companion docs: `BOOSTOPT_Surfaces` (all delivery surfaces), `BOOSTOPT.md` (the concept), `BOOSTOPT_Roadmap` (where #18 sits). One fact, one home.*
