# BOOSTOPT — the verified C++ optimizer

**BOOSTOPT proposes an optimization to your C++ and applies it *only* after proving the change is byte-identical in behavior AND measurably faster.** An untrusted proposer (a local LLM, or deterministic rules) suggests changes; a trusted gate re-compiles, differential-tests, runs sanitizers, and benchmarks each one — and keeps only what passes.

> **BOOSTOPT proves your code on *your* machine — the source never leaves your box.**

[![CI](https://github.com/Boostinorbit-com/Boostopt/actions/workflows/ci.yml/badge.svg)](https://github.com/Boostinorbit-com/Boostopt/actions/workflows/ci.yml)
&nbsp;License: Proprietary (all rights reserved) &nbsp;·&nbsp; Status: beta (v0, C++)

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
pip install boostopt          # installs the `boostopt` command

# Optimize a file: really compiles, differential-tests, runs ASan/UBSan, and benchmarks.
boostopt optimize examples/packet_stats.cpp --offline
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
- Neither is possible (no Ollama, no base, a failed pull)? It falls back to configuring the plain `qwen2.5-coder:7b`, so the project never points at a model that doesn't exist.

The recipe — and its Apache-2.0 attribution to Qwen — ships in the wheel at `boostopt/runtime/models/boostopt2.5-coder.Modelfile`. Any other model works too: `--llm-model llama3:8b` is pulled by name, unmodified.

## What you get

- **Correctness you can trust** — differential testing on fuzzed inputs *plus* ASan/UBSan/TSan, so it catches undefined behavior a passing test suite would miss.
- **Actually faster** — a measured Pareto vector (p50, p99, **peak memory**), not one guessed metric.
- **On your machine** — a local model, or your own key; the source never leaves your box.
- **Beyond a compiler's reach** — data-structure swaps, signature changes, container-type changes.
- **Inspectable** — read the diff and the proof; untrusted binaries run in a sandbox.

BOOSTOPT's built-in **wedge test** — 14 pre-registered cases — shows it **accepts** real wins (reserve, `map`→`unordered_map`, `list`→`vector`, pass-by-const-ref…) **and rejects** deliberately-broken ones (an out-of-bounds write that passes the diff test but ASan catches; a memoization that's faster but blows the memory budget). Run it yourself: `python -m wedge.run`.

## Commands

```bash
boostopt init                       # set up a .boostopt/ workspace (like `git init`) + prep the local model
boostopt analyze  foo.cpp           # non-destructive: what would you optimize, and why
boostopt optimize foo.cpp --apply   # verify, then write the accepted change (transactional, sound-only)
boostopt optimize -p build/ --all   # whole codebase (a compile_commands.json)
boostopt report                     # the ledger — every accept/reject, its rung, its measured Δ
```

Key flags: `--offline` (rules) · `--model local|frontier` (LLM) · `--min-rung N` · `--metamorphic` · `--diff` · `--json` · `--jobs N`. Full reference: [`Docs/BOOSTOPT_Flags.md`](Docs/BOOSTOPT_Flags.md).

## Install

**From PyPI** (recommended):
```bash
pip install boostopt
```

**From source** (Python 3.11+):
```bash
git clone https://github.com/Boostinorbit-com/Boostopt && cd Boostopt
pip install -e '.[dev]'
boostopt analyze --verify-setup     # checks clang, sanitizers, ccache, linker
```

**Docker** (zero setup — bundles clang + sanitizers):
```bash
docker build -t boostopt .
docker run --rm -v "$PWD:/src" -w /src boostopt optimize examples/packet_stats.cpp --offline
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
| [BOOSTOPT.md](Docs/BOOSTOPT.md) | the idea, the invariant, prior art — *why it's sound* |
| [BOOSTOPT_Architecture.md](Docs/BOOSTOPT_Architecture.md) | the engine + the C++ instance — *how it's built* |
| [BOOSTOPT_Surfaces.md](Docs/BOOSTOPT_Surfaces.md) | CLI / CI / IDE / config — *what you run* |
| [BOOSTOPT_Roadmap.md](Docs/BOOSTOPT_Roadmap.md) | what's done, what's next |

Every `.md` has a styled `.html` twin for reading in a browser.

## License

**Proprietary — all rights reserved** (see [LICENSE](LICENSE)). Pre-release software under active development; not licensed for use, copying, or distribution. The licensing terms for any future public release are reserved and will be decided at that time.
