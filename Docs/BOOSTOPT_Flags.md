# BOOSTOPT — CLI Flag Reference

> **Auto-generated** from `boostopt --help` by `tools/gen_flags.py`. Do not edit by hand — regenerate with:
> ```
> python tools/gen_flags.py --write Docs/BOOSTOPT_Flags.md
> ```
> These are the flags **actually wired today**. The design roadmap (including planned flags) lives in `BOOSTOPT_Surfaces.md`.

## `boostopt` (global)

**options**

| flag | description |
|---|---|
| `-V, --version` | show program's version number and exit |

## `boostopt analyze`

Inspect optimization opportunities without changing anything.

**target selection**

| flag | description |
|---|---|
| `<path>` | a source file (single-file mode); omit with --all |
| `-p, --compile-commands DB` | compile_commands.json, or a build dir containing one — the compilation database (canonical source of flags) |
| `--all` | optimize every translation unit in the database (requires -p) |

**verification policy**

| flag | description |
|---|---|
| `--min-rung N` | correctness rung required to accept (default 3 = sanitizers) |
| `--fast` | skip the Rung-3 sanitizer for speed (UNSOUND — verdict is labeled) |
| `--offline` | use the deterministic rule proposer (no model / API) |
| `--model NAME` | proposer model (frontier \| local \| rules) |

**selection & tuning**

| flag | description |
|---|---|
| `--transforms GLOB` | only run transforms matching GLOB (comma-separated globs) |
| `--list-transforms` | list the available transforms and exit |
| `--min-speedup PCT` | reject gains below PCT%% (default 2) |
| `--changed REF` | codebase mode: only verify TUs git changed vs REF (default: working tree) |
| `--jobs, -j N` | codebase mode: process N translation units in parallel (default 1) |
| `--reps N` | benchmark repetitions (upper bound when adaptive) |
| `--reps-min N` | adaptive floor — escalate to --reps only if the result is borderline (default 5) |
| `--no-adaptive` | always run the full --reps (disable early-stop when the gain is unambiguous) |
| `--fp-tolerance REL` | accept FP output within this relative tolerance (item #1b; default 0 = exact) |
| `--fuzz N` | seeded fuzzed correctness inputs beyond the fixed edge cases (default 1000) |
| `--seed N` | PRNG seed for fuzzed inputs — deterministic, reproducible verdicts (default 0) |
| `--objectives LIST` | comma-separated Pareto objectives to gate on (e.g. p50,p99,peak_memory) |
| `--config KEY=VAL` | inline config override (repeatable) |
| `--verify-setup` | check the toolchain (clang, sanitizers, ccache, linker) and exit |

**output & execution**

| flag | description |
|---|---|
| `--diff` | print the full unified diff of each accepted change |
| `--json` | machine-readable output |
| `--fail-on WHAT` | #18 CI gate: force the exit code — none (always 0; findings are advisory) \| any (exit 1 if a verified optimization was found). Omit for the default codes (0=found, 1=none, 3=all-rejected) |
| `--quiet, -q` | only print accepted changes (and their diffs) |
| `--no-color` | disable colored output |
| `--no-daemon` | run in-process even if a boostopt daemon is available |
| `--config-file FILE` | project config (default .boostopt.toml) |
| `--profile FILE` | real profile (perf --stdio / gprof / json / 'symbol cost') to pick the hot function |
| `--test-command CMD` | build+run the project's own tests to re-confirm each accepted change (exit 0 = pass) |
| `--test-dir DIR` | cwd for --test-command (default: the target file's directory) |
| `--test-timeout SEC` | timeout for --test-command / --bench-command runs (default 600) |
| `--bench-command CMD` | 2A: build+run a project bench, timed as the perf signal for functions the harness can't reach |
| `--bench-dir DIR` | cwd for --bench-command (default: the target file's directory) |
| `--bench-runs N` | 2A: median-of-N timings of the bench per side (default 5) |
| `--build-command CMD` | 2A: build step run ONCE before timing, so the bench is timed run-only (e.g. 'make') |
| `--ctest-dir DIR` | 2A-1: a CMake build dir — auto-discover the test/bench commands from ctest |
| `--metamorphic` | 2D: also run the metamorphic property rung (Rung 2) — rejects a change that breaks permutation-invariance |
| `--no-sandbox` | #13: run untrusted binaries WITHOUT bwrap/cgroup isolation (escape hatch; UNSAFE) |
| `--sandbox-mem MB` | #13: cgroup memory cap (MB) for isolated runs (default 2048) |
| `--budget SPEC` | #12: per-run LLM spend cap — tokens ('500k'), money ('$2'), or time ('90s') |
| `--budget-per-hotspot SPEC` | #12: per-hotspot LLM spend sub-limit (same SPEC forms as --budget) |
| `--llm-model NAME` | #10: LLM name for --model local\|frontier (default boostopt2.5-coder:7b) |
| `--llm-url URL` | #10: LLM host base URL (default http://127.0.0.1:11434 — local Ollama) |
| `--candidates N` | #11: ask the LLM for N rewrites per hotspot; gate each, keep the best (default 1) |
| `--refine` | re-run the proposer even if a cached best exists, and keep whichever is faster (the cached 'high score' only ever rises) |
| `--no-cache` | ignore the best-so-far rewrite cache — recompute from scratch this run |
| `--boostopt-token TOKEN` | PREMIUM: entitlement token for --model hosted (or set BOOSTOPT_TOKEN) |
| `--hosted-url URL` | PREMIUM: boostopt_server base URL for --model hosted (default http://127.0.0.1:8724) |

## `boostopt optimize`

Find, verify, and apply performance improvements.

**target selection**

| flag | description |
|---|---|
| `<path>` | a source file (single-file mode); omit with --all |
| `-p, --compile-commands DB` | compile_commands.json, or a build dir containing one — the compilation database (canonical source of flags) |
| `--all` | optimize every translation unit in the database (requires -p) |

**verification policy**

| flag | description |
|---|---|
| `--min-rung N` | correctness rung required to accept (default 3 = sanitizers) |
| `--fast` | skip the Rung-3 sanitizer for speed (UNSOUND — verdict is labeled) |
| `--offline` | use the deterministic rule proposer (no model / API) |
| `--model NAME` | proposer model (frontier \| local \| rules) |

**apply**

| flag | description |
|---|---|
| `--apply` | write accepted, sound changes to source |
| `--dry-run` | preview only — never write (the default) |
| `--backup` | save <file>.bak before overwriting |
| `--force` | apply even an unsound (--fast) result |
| `--export FILE` | write accepted diffs to FILE instead of applying |
| `--apply-from FILE` | apply a diff set written by --export (uses `patch`) |
| `--emit-patches DIR` | 2C: write a ranked, git-apply-able patch series + REPORT.md to DIR |

**selection & tuning**

| flag | description |
|---|---|
| `--transforms GLOB` | only run transforms matching GLOB (comma-separated globs) |
| `--list-transforms` | list the available transforms and exit |
| `--min-speedup PCT` | reject gains below PCT%% (default 2) |
| `--changed REF` | codebase mode: only verify TUs git changed vs REF (default: working tree) |
| `--jobs, -j N` | codebase mode: process N translation units in parallel (default 1) |
| `--reps N` | benchmark repetitions (upper bound when adaptive) |
| `--reps-min N` | adaptive floor — escalate to --reps only if the result is borderline (default 5) |
| `--no-adaptive` | always run the full --reps (disable early-stop when the gain is unambiguous) |
| `--fp-tolerance REL` | accept FP output within this relative tolerance (item #1b; default 0 = exact) |
| `--fuzz N` | seeded fuzzed correctness inputs beyond the fixed edge cases (default 1000) |
| `--seed N` | PRNG seed for fuzzed inputs — deterministic, reproducible verdicts (default 0) |
| `--objectives LIST` | comma-separated Pareto objectives to gate on (e.g. p50,p99,peak_memory) |
| `--config KEY=VAL` | inline config override (repeatable) |
| `--verify-setup` | check the toolchain (clang, sanitizers, ccache, linker) and exit |

**output & execution**

| flag | description |
|---|---|
| `--diff` | print the full unified diff of each accepted change |
| `--json` | machine-readable output |
| `--fail-on WHAT` | #18 CI gate: force the exit code — none (always 0; findings are advisory) \| any (exit 1 if a verified optimization was found). Omit for the default codes (0=found, 1=none, 3=all-rejected) |
| `--quiet, -q` | only print accepted changes (and their diffs) |
| `--no-color` | disable colored output |
| `--no-daemon` | run in-process even if a boostopt daemon is available |
| `--config-file FILE` | project config (default .boostopt.toml) |
| `--profile FILE` | real profile (perf --stdio / gprof / json / 'symbol cost') to pick the hot function |
| `--test-command CMD` | build+run the project's own tests to re-confirm each accepted change (exit 0 = pass) |
| `--test-dir DIR` | cwd for --test-command (default: the target file's directory) |
| `--test-timeout SEC` | timeout for --test-command / --bench-command runs (default 600) |
| `--bench-command CMD` | 2A: build+run a project bench, timed as the perf signal for functions the harness can't reach |
| `--bench-dir DIR` | cwd for --bench-command (default: the target file's directory) |
| `--bench-runs N` | 2A: median-of-N timings of the bench per side (default 5) |
| `--build-command CMD` | 2A: build step run ONCE before timing, so the bench is timed run-only (e.g. 'make') |
| `--ctest-dir DIR` | 2A-1: a CMake build dir — auto-discover the test/bench commands from ctest |
| `--metamorphic` | 2D: also run the metamorphic property rung (Rung 2) — rejects a change that breaks permutation-invariance |
| `--no-sandbox` | #13: run untrusted binaries WITHOUT bwrap/cgroup isolation (escape hatch; UNSAFE) |
| `--sandbox-mem MB` | #13: cgroup memory cap (MB) for isolated runs (default 2048) |
| `--budget SPEC` | #12: per-run LLM spend cap — tokens ('500k'), money ('$2'), or time ('90s') |
| `--budget-per-hotspot SPEC` | #12: per-hotspot LLM spend sub-limit (same SPEC forms as --budget) |
| `--llm-model NAME` | #10: LLM name for --model local\|frontier (default boostopt2.5-coder:7b) |
| `--llm-url URL` | #10: LLM host base URL (default http://127.0.0.1:11434 — local Ollama) |
| `--candidates N` | #11: ask the LLM for N rewrites per hotspot; gate each, keep the best (default 1) |
| `--refine` | re-run the proposer even if a cached best exists, and keep whichever is faster (the cached 'high score' only ever rises) |
| `--no-cache` | ignore the best-so-far rewrite cache — recompute from scratch this run |
| `--boostopt-token TOKEN` | PREMIUM: entitlement token for --model hosted (or set BOOSTOPT_TOKEN) |
| `--hosted-url URL` | PREMIUM: boostopt_server base URL for --model hosted (default http://127.0.0.1:8724) |

## `boostopt init`

Set up the .boostopt/ performance workspace (like git init) and prepare the local model.

**options**

| flag | description |
|---|---|
| `--model NAME` | local model to record as the project default (default: config llm_model) |
| `--pull` | build the model now via Ollama if missing — pulls its base (may download GBs), then re-tags |
| `--global` | also scaffold machine-wide defaults at ~/.config/boostopt/config.toml |

## `boostopt serve`

Run a warm background daemon so repeated runs are fast.

**options**

| flag | description |
|---|---|
| `--stop` | stop a running daemon |
