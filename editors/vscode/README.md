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
| `verto.model` | `rules` | Proposer: `rules` (deterministic, no network) · `local` (Ollama) · `frontier` (hosted). |
| `verto.compileCommands` | `""` | Path to `compile_commands.json` (optional; recommended for real codebases). |

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
