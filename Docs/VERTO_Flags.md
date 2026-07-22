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

**output & execution**

| flag | description |
|---|---|
| `--json` | machine-readable output |
| `--no-daemon` | run in-process even if a verto daemon is available |
| `--config-file FILE` | project config (default .verto.toml) |
| `--profile FILE` | profile data to guide hotspot selection (PLANNED — not yet consumed) |

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

**output & execution**

| flag | description |
|---|---|
| `--apply` | write accepted changes back to source (PLANNED — not yet implemented) |
| `--json` | machine-readable output |
| `--no-daemon` | run in-process even if a verto daemon is available |
| `--config-file FILE` | project config (default .verto.toml) |
| `--profile FILE` | profile data to guide hotspot selection (PLANNED — not yet consumed) |

## `verto serve`

Run a warm background daemon so repeated runs are fast.

**options**

| flag | description |
|---|---|
| `--stop` | stop a running daemon |
