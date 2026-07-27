# VERTO for VS Code (MVP)

Verified, correct-and-faster C++ optimizations in your editor. Every suggestion is
**proven behavior-identical** (differential test + sanitizers) and measurably faster
*before* it is ever shown — see the design note in [`Docs/VERTO_VSCode.md`](../../Docs/VERTO_VSCode.md).

> **Status: MVP scaffold.** Command + CodeLens + proof-on-hover + Apply. The CodeLens
> polish, on-save mode, and the "why skipped" view are follow-ons.

## What it does

1. **VERTO: Verify & Optimize Current File** (Command Palette) — runs `verto` on the
   open C++ file and collects the verified findings.
2. A **⚡ CodeLens** appears above each verified function: `verified −52% · Rung 3 — Apply`.
3. **Hover** the finding to see the proof: *byte-identical on N fuzzed inputs, sanitizers
   clean, measured p50.*
4. Click the lens to **Apply** the verified change (an undoable editor edit).

## Requirements

- The `verto` CLI reachable (see the `verto.command` setting), and `clang++` on PATH.
- A C++ file. For real projects, point `verto.compileCommands` at your
  `compile_commands.json` (CMake: `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`).

## Settings

| Setting | Default | Meaning |
|---|---|---|
| `verto.command` | `verto` | How to invoke the CLI. Use `python3 -m verto.surfaces.cli` to run from a checkout. |
| `verto.args` | `[]` | **Your choice of flags** passed to `verto optimize` — anything from `verto optimize --help`, e.g. `["--model","local","--min-rung","1","--metamorphic","--fuzz","5000"]`. The extension always adds `--json`. |
| `verto.compileCommands` | `""` | Convenience for the common `-p` flag: path to `compile_commands.json` (or put `-p <path>` in `verto.args`). |

**Config, two layers.** Keep *project policy* (rungs, transforms, objectives, budget…) in **`.verto.toml`** — it's read automatically and shared by the CLI, CI, and this extension, so all three behave identically. Use **`verto.args`** for *editor-specific* overrides on top. The extension never forces policy flags; unset knobs fall through to `.verto.toml`.

## Run profiles — `.verto.json` (team-shared, committed)

Rather than one fixed flag list, define **named profiles** in a `.verto.json` at your repo root (copy `.verto.json.example`). It's committed, so the whole team shares the same presets:

```json
{
  "default": "quick",
  "profiles": {
    "quick":    { "description": "fast, deterministic", "args": ["--model","rules","--fast"] },
    "thorough": { "description": "sanitizers + metamorphic + heavy fuzz",
                  "args": ["--model","rules","--min-rung","3","--metamorphic","--fuzz","5000"] },
    "ai":       { "description": "local LLM proposer", "args": ["--model","local","--candidates","3"] }
  }
}
```

- The **status bar** shows the active profile (`⚡ VERTO: quick`); click it — or run **"VERTO: Select Optimization Profile"** — to switch.
- **"Verify & Optimize"** then runs with that profile's flags.
- No `.verto.json`? It falls back to the `verto.args` setting.

## Develop / run locally

```bash
cd editors/vscode
npm install
npm run compile        # type-checks + emits out/
npm run test:core      # runs the pure-logic tests (no editor needed)
# then press F5 in VS Code to launch an Extension Development Host
```

Package a `.vsix` with [`@vscode/vsce`](https://github.com/microsoft/vscode-vsce):
`npx @vscode/vsce package`.

## How it's built

The extension is a **thin client**: all verification is the `verto` CLI. `src/core.ts`
holds the pure logic (parse `--json`, map diffs to edits, render the proof) and is
unit-tested off the editor; `src/extension.ts` is the VS Code glue (command, CodeLens,
hover, `WorkspaceEdit`). One `Verdict`, many renderers — the same payload the CLI and
CI Action render.
