# VERTO — CLI Flag Reference

> **Auto-generated** from `verto --help` by `tools/gen_flags.py`. Do not edit by hand — regenerate with:
> ```
> python tools/gen_flags.py --write Docs/VERTO_Flags.md
> ```
> These are the flags **actually wired today**. The design roadmap (including planned flags) lives in `VERTO_Surfaces.md`.

## `verto` (global)

**options**

| flag | description |
|---|---|
| `-V, --version` | show program's version number and exit |

## `verto analyze`

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
| `--reps N` | benchmark repetitions |
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
| `--quiet, -q` | only print accepted changes (and their diffs) |
| `--no-color` | disable colored output |
| `--no-daemon` | run in-process even if a verto daemon is available |
| `--config-file FILE` | project config (default .verto.toml) |
| `--profile FILE` | real profile (perf --stdio / gprof / json / 'symbol cost') to pick the hot function |
| `--test-command CMD` | build+run the project's own tests to re-confirm each accepted change (exit 0 = pass) |

## `verto optimize`

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

**selection & tuning**

| flag | description |
|---|---|
| `--transforms GLOB` | only run transforms matching GLOB (comma-separated globs) |
| `--list-transforms` | list the available transforms and exit |
| `--min-speedup PCT` | reject gains below PCT%% (default 2) |
| `--changed REF` | codebase mode: only verify TUs git changed vs REF (default: working tree) |
| `--jobs, -j N` | codebase mode: process N translation units in parallel (default 1) |
| `--reps N` | benchmark repetitions |
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
| `--quiet, -q` | only print accepted changes (and their diffs) |
| `--no-color` | disable colored output |
| `--no-daemon` | run in-process even if a verto daemon is available |
| `--config-file FILE` | project config (default .verto.toml) |
| `--profile FILE` | real profile (perf --stdio / gprof / json / 'symbol cost') to pick the hot function |
| `--test-command CMD` | build+run the project's own tests to re-confirm each accepted change (exit 0 = pass) |

## `verto serve`

Run a warm background daemon so repeated runs are fast.

**optional arguments**

| flag | description |
|---|---|
| `--stop` | stop a running daemon |
