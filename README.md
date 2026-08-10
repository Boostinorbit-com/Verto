# BOOSTOPT — the verified C++ optimizer

**BOOSTOPT proposes an optimization to your C++ and applies it *only* after proving the change is byte-identical in behavior AND measurably faster.** An untrusted proposer (a local LLM, or deterministic rules) suggests changes; a trusted gate re-compiles, differential-tests, runs sanitizers, and benchmarks each one — and keeps only what passes.

> **BOOSTOPT proves your code on *your* machine — the source never leaves your box.**

[**boostopt.com**](https://boostopt.com) &nbsp;·&nbsp; [Docs](https://boostopt.com/docs) &nbsp;·&nbsp; License: Commercial EULA — free tier, unlimited local + CI use &nbsp;·&nbsp; Status: beta (v0, C++)

---

## The one invariant

BOOSTOPT accepts a change **if and only if**:

```
correctness.rung ≥ min_rung   AND   performance.pareto_pass
```

- **Correct** — a graded ladder: Rung 1 differential test on fuzzed held-out inputs → Rung 3 **AddressSanitizer / UBSan / ThreadSanitizer** clean → (opt-in) Rung 2 metamorphic properties.
- **Faster** — a Pareto vector (**p50, p99, peak memory**) measured by real benchmarking, not guessed.

The proposer can be wrong, slow, or adversarial — a bad suggestion is a *rejected proposal*, never a wrong accept. That's the whole design.

## Quickstart (60 seconds)

Requires **`clang++`** with sanitizers (that's the one real system dependency — `libclang` ships with the pip package).

```bash
# One command — installs the tool, Ollama, and the local model:
curl -fsSL https://boostopt.com/install.sh | sh

# Or just the Python tool (CI, containers, or bring your own model):
pip install boostopt          # installs the `boostopt` command

# Prove it on a bundled sample: really compiles, differential-tests, runs ASan/UBSan, benchmarks.
boostopt demo
```

Output (numbers vary by machine — the *acceptance* is what's guaranteed):

```
  reserve_before_pushback  →  ACCEPT
    correctness: Rung 3 (clean)
    performance: p50 2.22 ms (-68.0%)  pareto=True
    ✓ applied to source        (with --apply; dry-run by default)
```

`--offline` uses the deterministic rule proposer (no model, no key). To use a **local LLM** instead — free, private, nothing leaves your machine:

```bash
boostopt init --pull                           # one-time: build the local model (see below)
boostopt optimize hot.cpp --model local        # via a local Ollama
```

### The local model

BOOSTOPT's default local model is **`boostopt2.5-coder:7b`** — [`qwen2.5-coder:7b`](https://ollama.com/library/qwen2.5-coder) (Apache-2.0) re-tagged with our optimize system prompt and sampling baked in. It is *not* a second download: `ollama create` re-labels weights Ollama already has, so only the base model crosses the wire.

`pip install boostopt` **does not** touch Ollama — Python wheels run no install-time code, and a 2-second install shouldn't become a multi-gigabyte one. The model is built by `boostopt init`, which needs [Ollama](https://ollama.com) installed:

- `boostopt init` — if the base is already pulled, it re-tags immediately (seconds, no download).
- `boostopt init --pull` — pulls the base first (~4 GB), then re-tags.
- `boostopt init --pull --install-ollama` — installs Ollama too, if it's missing. It shows the exact command, asks first, and needs sudo (Ollama runs as a system service). Opt-in by design: a plain `--pull` never escalates, and a non-interactive shell — CI, a pipe, a hook — is always treated as "no".
- Neither is possible (no Ollama, no base, a failed pull)? `init` says so and records the plain `qwen2.5-coder:7b` in `.boostopt/model` — the git-ignored note of what this machine actually has. The committed `.boostopt.toml` still asks for `boostopt2.5-coder:7b`, because a shared config records the project's intent, not one laptop's state. Re-run `boostopt init --pull` once Ollama is available and the pointer catches up.

The recipe — and its Apache-2.0 attribution to Qwen — ships in the wheel at `boostopt/runtime/models/boostopt2.5-coder.Modelfile`. Any other model works too: `--llm-model llama3:8b` is pulled by name, unmodified.

### Removing BOOSTOPT

`pip uninstall boostopt` deletes the Python package and nothing else — wheels have no uninstall hook, the same reason pip can't install Ollama. Use the command that ships alongside it:

```bash
boostopt-uninstall                          # dry run: prints exactly what would go
boostopt-uninstall --yes                    # models we built, workspace, config, then the package
boostopt-uninstall --yes --remove-ollama    # also tears down Ollama, if WE installed it
```

Every install is recorded in `~/.local/state/boostopt/installed.json`, and uninstall removes **only what that receipt claims as ours**. An Ollama that was already on your machine, or a `qwen2.5-coder:7b` you pulled for your own work, is listed as *left alone* and never touched. The Ollama teardown needs sudo, so it prints the commands and asks first — and the model store is left in place, since it's gigabytes a reinstall picks straight back up.

## What you get

- **Correctness you can trust** — differential testing on fuzzed inputs *plus* ASan/UBSan/TSan, so it catches undefined behavior a passing test suite would miss.
- **Actually faster** — a measured Pareto vector (p50, p99, **peak memory**), not one guessed metric.
- **On your machine** — a local model, or your own key; the source never leaves your box.
- **Beyond a compiler's reach** — data-structure swaps, signature changes, container-type changes.
- **Inspectable** — read the diff and the proof; untrusted binaries run in a sandbox.

BOOSTOPT's built-in **wedge test** — 14 pre-registered cases — shows it **accepts** real wins (reserve, `map`→`unordered_map`, `list`→`vector`, pass-by-const-ref…) **and rejects** deliberately-broken ones (an out-of-bounds write that passes the diff test but ASan catches; a memoization that's faster but blows the memory budget). Run it yourself: `python -m wedge.run`.

## Commands

```bash
boostopt demo                       # prove it on a bundled sample — no setup, no model
boostopt init                       # set up a .boostopt/ workspace (like `git init`) + prep the local model
boostopt analyze  foo.cpp           # non-destructive: what would you optimize, and why
boostopt optimize foo.cpp --apply   # verify, then write the accepted change (transactional, sound-only)
boostopt optimize -p build/ --all   # whole codebase (a compile_commands.json)
boostopt report                     # the ledger — every accept/reject, its rung, its measured Δ
boostopt-uninstall                  # remove the models/workspace/config we created, then the package
```

Key flags: `--offline` (rules) · `--model local|frontier` (LLM) · `--min-rung N` · `--metamorphic` · `--diff` · `--json` · `--jobs N`. Full reference: <https://boostopt.com/docs/flags>.

## Install

**From PyPI** (recommended):
```bash
pip install boostopt
```

**One command** (installs the tool, Ollama, and the local model):
```bash
curl -fsSL https://boostopt.com/install.sh | sh
```

**Check your toolchain** — `clang++` with sanitizers is the one hard requirement:
```bash
boostopt analyze --verify-setup     # checks clang, sanitizers, ccache, linker
```

Optional extras: a **local LLM** via [Ollama](https://ollama.com) (`--model local`); **bubblewrap** for network/filesystem sandboxing of untrusted binaries; **ccache** for faster repeat runs. `boostopt analyze --verify-setup` reports what's present.

## How it works

A four-stage loop, driven by `engine/orchestrator.py`:

```
 Evidence   →   Proposal      →   Mutate    →   Verify
 (sensor)       (LLM / rules)     (splice)      (the GATE: compile · diff-test ·
   │                                             sanitizers · benchmark)  ─→ accept ⟺ invariant
   └───────────────────────── learn (ledger) ─────────────────────────────┘
```

Untrusted binaries run in a **bubblewrap sandbox** (no network, read-only filesystem, cgroup memory cap). The LLM path sends only the hot function's source and re-verifies whatever comes back, so the model choice can never cause a wrong accept.

## Status

**v0 (beta) — the AI optimizer runs end to end, locally.** The gate is real; a local `qwen3` produced a rewrite the hand-coded transforms lack and the gate verified it at −85%. CI is green on GitHub Actions (Python 3.11/3.12, full suite + the wedge on every push).

- ✅ Trusted gate (differential + ASan/UBSan/TSan; Pareto vector; opt-in metamorphic)
- ✅ LLM proposer (local Ollama or any OpenAI-compatible host), best-of-N, cost cap, sandbox
- ✅ `boostopt init` workspace, codebase mode, patch export, CI
- ⬜ Next: more languages (Axis A), formal verification (Alive2), hosted/CI product surfaces

**Scope:** v0 is **C++** and **Linux**. Multi-language (Python → Rust / Java / Go / JS) is designed for but not built.

## Documentation

| Doc | For |
|---|---|
| [Overview](https://boostopt.com/docs/overview) | the idea, the invariant, prior art — *why it's sound* |
| [Architecture](https://boostopt.com/docs/architecture) | the engine + the C++ instance — *how it's built* |
| [Surfaces](https://boostopt.com/docs/surfaces) | CLI / CI / IDE / config — *what you run* |
| [Flags](https://boostopt.com/docs/flags) | the complete, generated flag reference |

## License

**Commercial licence** — see the `LICENSE` file included in the distribution, or <https://boostopt.com/license>.

The **free tier** is licensed for use on any number of machines you own or control, including internal commercial use and CI. What it does *not* grant is redistribution, modification, or reverse engineering. **Premium features** (the hosted optimization service) require a subscription key.

BOOSTOPT is proprietary: the source is not published, and the package you install is licensed, not sold.
