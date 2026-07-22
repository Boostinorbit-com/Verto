# VERTO — Surfaces & Delivery

**How VERTO is delivered to a user: the CLI, the CI action, the IDE extension, and beyond.**

This document owns the *surface specs* — what each front-end looks like and does.
It does **not** own the Engine API those surfaces call; that lives in `VERTO_Architecture` (the "how it's built" doc).
For the *concepts* behind the work each surface triggers, see `VERTO.md`.

> **Scope note:** v0 targets **C++**. Multiple languages (Python → Rust / Java / Go / JS) are **Axis A** in `VERTO.md` §12 — planned and architected for, but not yet built. Everything below is C++ today.

---

## The one principle

Every surface is a **thin client over one Engine API.**
A surface does exactly three things: (1) collect the user's intent (which files, which flags), (2) call the Engine API, (3) render the structured result it gets back.
It contains **no optimization logic, no verification, and no LLM calls** — all of that lives in the engine, behind the API.

Every surface calls the same three operations:

- **`analyze`** — find hotspots and candidate transforms and explain them; changes nothing.
- **`optimize`** — propose → verify (correct AND faster) → optionally apply; returns a list of `Verdict`s.
- **`report`** — read the Ledger; summarise what's been accepted/rejected and the measured gains.

```
   CLI        VS Code ext      CI action      Web dashboard      SDK
    │             │               │                │              │
    └─────────────┴───────┬───────┴────────────────┴──────────────┘
                          ▼
             Engine API  (analyze · optimize · report)     ← spec'd in VERTO_Architecture
                          ▼
                 Orchestrator → the four-stage loop
```

**Why this matters, concretely:** the same `reserve()` finding shows up as a CLI table row, a PR comment, and an editor hint — because all three call `optimize()` and render the *same* `Verdict` payload.
Build the engine once and every surface inherits it; the dangerous parts (the trusted gate, the sandbox) live in one audited place instead of being re-implemented — and mis-implemented — per UI.

**Consequence:** the engine is built once; each new surface is a few days of glue, not a rebuild. No optimization logic ever lives in a surface.

---

## Staged overview

| Surface | What it is | When | Why |
|---|---|---|---|
| **CLI** (`verto analyze / optimize --apply / report`) | terminal tool | **v0** | simplest; proves the engine end-to-end |
| **CI action** (GitHub Action / GitLab CI) | runs on a PR, comments verified findings; also **prevention mode** (contracts-in-CI) | v1 | highest leverage; matches Codeflash's GH Action |
| **VS Code / IDE extension** | inline verified suggestions, one-click apply | v1 | where developers live; matches Codeflash's VS Code plugin |
| **Web dashboard** | team view of where code is slow, trends over time | v2 | reads the Ledger; a team/management surface |
| **Network service** | shared verified-transform backend (Axis E) | vision | the flywheel |
| **SDK / library** | embed the engine programmatically | optional | for power users / integration |

**Build discipline:** only the **CLI** ships in v0.
Everything else is designed as a client of the same API, but built later — the engine must work before any surface is worth polishing.

---

## v0 — CLI (fully specified)

The reference surface. Every other surface mirrors its verbs and its JSON output.

### Commands

```
verto analyze  <path> [-p DB] [--all] [--min-rung N] [--offline] [--json]
    Non-destructive. Detect hotspots + candidate transforms and explain them.
    Writes nothing. The "what would you do?" command.

verto optimize <path> [-p DB] [--all] [--min-rung N] [--fast] [--offline] [--json] [--apply]
    Propose → verify (correct AND faster) → keep only what passes the gate.
    default        : dry-run; prints the diffs it WOULD write.
    with --apply   : writes the accepted diffs to your source. (planned)

verto report   [--json]
    Read the Ledger; show accepted/rejected episodes, rungs, and measured gains.

verto serve    [--stop]
    Run a warm background daemon (Python + libclang loaded once) so later
    optimize/analyze calls skip startup. --stop stops it; pass --no-daemon to
    any call to bypass it.

# -p / --compile-commands supplies the compilation database (a compile_commands.json or a
# build dir). Required to compile real multi-file C++. Generate via CMake:
# -DCMAKE_EXPORT_COMPILE_COMMANDS=ON. A self-contained single file needs no -p.
```

### Conventions

VERTO uses **GNU/POSIX-style flags as the base, with LLVM-friendly affordances** — familiar to `git`/`cargo` users *and* to `clang-tidy` users. (Rationale: VERTO has subcommands and a Python engine, where `llvm::cl`'s single-dash-long style fights the grain; but the audience is LLVM-native, so we adopt its habits where they help.)

- **Long options** are double-dash and canonical: `--min-rung`, `--compile-commands`.
- **Short options** for the common few: `-p`, `-j`, `-v`.
- **Values** accept either form: `--min-rung 3` **or** `--min-rung=3` (LLVM users reflexively type `=`).
- **Booleans** pair with a negation: `--sandbox` / `--no-sandbox`.
- **List flags** take comma-separated values or repeat: `--transforms reserve,unordered-map` or `--transforms reserve --transforms unordered-map`.
- **Forgiving:** a single dash on a long option is accepted (`-min-rung`, like `llvm::cl`), but double-dash is the documented form.

**Raw compiler flags pass through after `--`** — the clean way to stay LLVM-native without polluting VERTO's own namespace:

```
verto optimize hist.cpp -p build/ --min-rung 3 -- -O3 -std=c++20 -Iinclude -DNDEBUG
                                                └──────── verbatim to clang ────────┘
```

**Flag names mirror `clang-tidy`** where they overlap, so muscle memory transfers (this shows *naming intent*; see the Flags table below for what's actually built — several are still planned):

| VERTO | clang-tidy analog | shared idea |
|---|---|---|
| `-p, --compile-commands` | `-p` | compilation database |
| `--transforms` / `--list-transforms` | `--checks` / `--list-checks` | select what runs |
| `--apply` | `--fix` | write changes to source |
| `--export FILE` / `--apply-from FILE` | `--export-fixes` / clang-apply-replacements | decouple propose & apply |
| `--config-file .verto.toml` | `--config-file .clang-tidy` | project config |
| `--format` | `--format-style` | reformat after edit |
| `--quiet` | `--quiet` | suppress noise |

### Flags

Grouped by concern. **Status:** ✅ wired (v0 CLI flag) · ⚙️ config-only (settable in `.verto.toml` today, no CLI flag yet) · ⚠️ flag present but not yet functional · **v1** / **later** planned. `VERTO_Flags.md` (generated from the parser) is the exact ✅ set; this table is the fuller roadmap. Each flag maps to a parameter of the Engine API (spec'd in `VERTO_Architecture`).

**Target selection**

| Flag | Meaning | Stage |
|---|---|---|
| `<path>` | file or directory to work on | ✅ |
| `--all` | whole codebase (every TU in the database) | ✅ |
| `-p, --compile-commands PATH` | **`compile_commands.json` (or build dir) — required to compile real C++** | ✅ |
| `--function NAME` | limit to one function (hotspot is auto-selected today) | v1 |
| `--changed [--base REF]` | only git-changed code (the CI workhorse) | v1 |
| `--include` / `--exclude GLOB` | scope by path glob | v1 |
| `--line-filter` | restrict to `file:line` ranges | later |

**Evidence / profiling**

| Flag | Meaning | Stage |
|---|---|---|
| `--profile FILE` | runtime profile to guide selection | ⚠️ |
| `--profiler perf\|gbench\|xray` | which profiler produced it | v1 |
| `--top N` / `--min-hotspot PCT` | only touch the hottest code; ignore cold | v1 |
| `--no-profile` | static facts only (no runtime) | v1 |

**Proposal / model**

| Flag | Meaning | Stage |
|---|---|---|
| `--model NAME` | LLM backend (frontier now, local later) | ✅ |
| `--offline` | rules-only, no LLM (deterministic; good for CI) | ✅ |
| `--candidates N` | try N proposals per hotspot; keep the best **verified** one | ⚙️ |
| `--transforms GLOB` (`--list-transforms` planned) | enable/disable transforms | ⚙️ |
| `--budget TOKENS\|$\|TIME` | hard cost cap on exploration | v1 |

**Correctness rigor** *(VERTO-specific — this is the differentiator)*

| Flag | Meaning | Stage |
|---|---|---|
| `--min-rung N` | auto-apply only at correctness Rung ≥ N (default 3) | ✅ |
| `--fast` | skip the Rung-3 sanitizer for speed — **UNSOUND**, verdict labeled | ✅ |
| `--fuzz-inputs N` | held-out inputs for the differential test | ⚙️ |
| `--seed N` | reproducible fuzzing / benchmarking | ⚙️ |
| `--sanitizers address,undefined,thread` | which sanitizers the gate runs (auto-detected today) | v1 |

**Performance gate** *(the Performance Vector, made controllable)*

| Flag | Meaning | Stage |
|---|---|---|
| `--min-speedup PCT` | reject gains below threshold (kills noise) | ⚙️ |
| `--reps N` (`--warmup N` planned) | benchmark repetitions | ⚙️ |
| `--objectives p50,p99,memory,size` | which Performance-Vector dimensions count | ⚙️ |
| `--allow-regression mem=5%` | per-dimension Pareto budget | ⚙️ |
| `--significance 0.01` | required statistical confidence | v1 |
| `--baseline FILE` | compare against a saved baseline | v1 |

**Apply / output**

| Flag | Meaning | Stage |
|---|---|---|
| `--json` | machine schema (array of `Verdict`) | ✅ |
| `--apply` | write accepted diffs (default is dry-run/preview) | ⚠️ |
| `--diff` | emit patch output | v1 |
| `--export FILE` | write proposed patches to a file (review/CI) | v1 |
| `--apply-from FILE` | apply a previously exported/reviewed set | v1 |
| `--format` | run clang-format on applied changes | v1 |
| `--interactive` | confirm each change | later |

**CI / automation**

| Flag | Meaning | Stage |
|---|---|---|
| `--fail-on left-on-table\|regression\|contract-violation` | control CI failure | v1 |
| `--mode optimize\|prevent` | prevention mode (contracts-in-CI) | v1 |
| `--comment` | post PR comments | v1 |
| `--no-color` | plain CI logs (the `NO_COLOR` env var is already honored) | v1 |

**Config / setup / safety**

| Flag | Meaning | Stage |
|---|---|---|
| `--config-file .verto.toml` | reproducible config | ✅ |
| `--no-daemon` | run in-process, ignore a warm `verto serve` daemon | ✅ |
| `-V, --version` | print the VERTO version | ✅ |
| `--sandbox` / `--no-sandbox` | isolate verification runs | ⚙️ |
| `--timeout SEC` | per-run time limit | ⚙️ |
| `--config KEY=VAL` | inline config override | v1 |
| `--verify-setup` | check the toolchain is present (clang, sanitizers, profiler, benchmark) | v1 |
| `--no-network`, `--cache` / `--no-cache`, `--max-changes N`, `--jobs N`, `--quiet`, `-v/-vv` | isolation, caching, limits & noise | v1 |

### Exit codes (so CI can branch on them)

| Code | Meaning |
|---|---|
| `0` | success — at least one verified change found (or applied) |
| `1` | ran fine, but **no verified opportunity** found |
| `2` | error (build failure, missing tool, bad path) |
| `3` | candidates found but **all rejected** by the gate (correctness or perf) |

### Output — human and machine

Human (default): a per-hotspot block — the finding, the proposed diff, and the **verification box** (rung + speedup vector).
Machine (`--json`): an array of `Verdict` objects (schema owned by `VERTO_Architecture`).
**Every surface emits this same `Verdict` JSON** — the CI comment, the IDE hint, and the dashboard all render the same underlying data.

### Example session

```
$ verto optimize packet_stats.cpp --profile perf.data

  build_histogram()  — 79% runtime, 2.3M calls
  proposal: reserve(n) before the push_back loop        [contract: bound loop-invariant ✓]
  ┌ verification ─────────────────────────────────────────────┐
  │ correctness:  1000 held-out inputs identical · UBSan clean │  Rung 3 ✓
  │ performance:  3.9 ms → 2.4 ms  (−38%)  · p99 ✓ · mem ✓      │  Pareto ✓
  └────────────────────────────────────────────────────────────┘
  ACCEPT — run with --apply to write the diff
```

---

## v1 — CI action (GitHub Action / GitLab CI)

Runs VERTO automatically on every pull request, so optimization becomes part of code review instead of a separate chore.

**How it works, step by step:**
1. The PR triggers the action.
2. It runs `verto optimize --changed --base <target-branch> -p compile_commands.json --json` — scoped to just the files the PR touched.
3. It parses the returned `Verdict` JSON and acts on it according to the mode.
4. It branches the build on the CLI's exit code.

**Two modes:**
- **`comment` (default, non-blocking):** posts each *verified* finding as a PR review comment — the diff, the measured gain, and the rung. The author clicks to apply. Informational; never fails the build.
- **`prevent` (blocking):** runs the **contracts as checks**. If new code re-introduces a pattern VERTO already fixed — e.g. a hot `push_back` loop with no `reserve` — the check **fails the build** (`--fail-on contract-violation`). This turns the optimizer into a regression *preventer*, the stickiest use.

**What the developer sees** — a bot comment on the PR:

```
🟢 VERTO — verified optimization in build_histogram()
   reserve(n) before the push_back loop
   −38% (3.9 → 2.4 ms) · p99 ✓ · mem ✓ · Rung 3 (UBSan clean)
   [ Apply suggestion ]   contract: loop bound is invariant
```

**Setup** (once): add the workflow YAML, commit a `compile_commands.json` (CMake `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`), set `min-rung`.
**Tech:** a thin YAML action wrapping the CLI — no engine logic; it just runs `verto` and renders `--json`.
**Why first among the v1 surfaces:** highest leverage, zero new UI, and the surface Codeflash leads with.

```yaml
# .github/workflows/verto.yml (sketch)
- uses: verto/optimize-action@v1
  with:
    paths: ${{ changed_files }}
    compile-commands: build/compile_commands.json
    min-rung: 3
    mode: comment        # or: prevent  (fails the build on regressions)
```

---

## v1 — VS Code / IDE extension

Brings verified suggestions into the editor, where developers already work.

**The experience, end to end:**
1. You open (or save) a C++ file.
2. In the background, VERTO analyses it and marks hot regions with a **gutter icon**.
3. You hover the icon → a card shows the **proposed diff** and the **verification box** (rung + speedup vector) — exactly what the CLI prints.
4. You click **Apply** → the change is written and (optionally) reformatted with clang-format.

**Only verified suggestions ever appear.** If a proposal fails the gate (wrong output, UB, or not actually faster), the developer never sees it — no raw LLM guesses, unlike a generic code assistant.

**How it's built:**
- The extension is **thin TypeScript** — pure presentation.
- It talks to a **local `verto` daemon** over an LSP-style JSON-RPC protocol.
- The daemon runs the engine (which needs the toolchain + `compile_commands.json`). The extension never invokes clang or an LLM itself.

**Latency:** analysis and verification (build + benchmark) take seconds, so they run **asynchronously** — results stream into the editor as they're verified; typing is never blocked.
**Config:** reads the project's `.verto.toml` (min-rung, transforms, profile source), so editor and CLI behave identically.
**Why:** developers live in the editor; parity with Codeflash's VS Code plugin.

---

## v2 — Web dashboard

A bird's-eye, read-only view for leads and performance teams — a reporting surface, not a coding tool.

**Where the data comes from:** it reads the **Ledger**, the append-only log every surface already writes to. Because every accept and reject from the CLI, CI, and IDE is recorded there, the dashboard needs **no new engine work** — it's a view over data that already exists.

**What it shows:**
- **Hotspot map** — where the codebase spends time, and where verified opportunities still remain.
- **Trend** — cumulative time / latency / memory saved, week over week.
- **Per-PR / per-author** — which verified optimizations landed and their measured gains.
- **Transform effectiveness** — which transforms produce the biggest verified wins (guides where to invest next).

**Tech:** a web app over a read-only API on the Ledger store (SQLite locally → Postgres as it grows).
**Audience:** engineering leads / management — the "is this paying off?" surface.
**Why v2:** it's only useful once the Ledger is populated — i.e. after the engine + CLI/CI have been in real use.

---

## Vision — Network service

The backend for **Axis E** — a shared store of verified `(transform, contract, rung)` tuples that makes every VERTO instance smarter.

**The flywheel:**
1. When any instance verifies and accepts a change, it can (opt-in) submit an **anonymized** tuple: the *pattern* it matched → the *transform*, its *precondition*, the *measured gain*, and the *rung*.
2. Other instances **query the network as priors** — so a fix proven on one codebase is proposed faster, and more confidently, on the next.
3. More users → more verified transforms → better proposals → more users. That's the moat a static compiler can never have.

**Why sharing is safe here** (and wouldn't be for a raw-LLM optimizer): what's shared is a **contract-checked, rung-graded transform**, not a code snippet. The precondition means another codebase can reuse it **only where its legality provably holds** — the network never lowers anyone's correctness bar.

**Privacy:** submissions are anonymized *patterns*, not your source; participation is opt-in; enterprises can run a **private, on-prem** network.
**Surface role:** a submit/query API; each engine's Ledger syncs to it.

```
POST /transforms   { pattern, transform, precondition, gain, rung }   # contribute
GET  /transforms?pattern=vector-grow-no-reserve                       # query as priors
```

**Why last:** trustworthy only once contracts + rungs are solid, and valuable only with many users. It is the moat — built after everything else works.

---

## Optional — SDK / library

The engine, importable — for when you want VERTO inside your own program instead of behind a CLI.

**What you get:** the same `analyze` / `optimize` / `report` operations as functions, returning `Verdict` objects you can inspect and act on programmatically.

```python
from verto import Engine

eng = Engine(compile_commands="build/compile_commands.json", min_rung=3)

report = eng.analyze("hist.cpp")            # non-destructive: hotspots + candidates
for v in eng.optimize("hist.cpp", apply=False):
    print(v.transform, v.rung, v.perf.p50_delta)   # inspect each Verdict
```

**Who uses it:** custom optimization pipelines, research harnesses, and — notably — the **Wedge Test judge**, which drives the engine's verification stage over competitors' outputs.
**Note:** no new capability — it's the same Engine API every surface calls, exposed as a library instead of a CLI.

---

## Cross-surface guarantees

Because every surface is a thin client of one engine, these hold everywhere — behavior never diverges between them:

- **One data contract.** Every surface renders the same `Verdict` JSON (transform, rung, perf-vector, diff). The CLI table, the PR comment, and the IDE hint are three *views* of one payload — so a finding reads identically wherever you see it.
- **One gate.** No surface can bypass the Invariant Gate or silently lower the correctness rung. `--min-rung` is explicit and logged — an IDE can't quietly ship a Rung-1 change dressed up as verified.
- **One Ledger.** Every accept/reject from every surface is recorded once, so `verto report` and the web dashboard always agree — there's no per-surface bookkeeping to drift.
- **One config.** `.verto.toml` is the single source for profile source, min-rung, budgets, and enabled transforms — change it once and every surface follows.
- **One engine version.** All surfaces run the same engine build, so a correctness or performance fix propagates everywhere at once.

---

*Surface specs live here; the Engine API they all call is specified in `VERTO_Architecture`; the concepts behind the work are in `VERTO.md`. One fact, one home.*
