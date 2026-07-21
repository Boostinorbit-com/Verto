# AION — AI Optimizer Network

An AI system that makes existing programs measurably faster by reasoning about them like a senior performance engineer, and that **only keeps a change it has proven to be both correct and faster.**

This repo holds both a **working v0 engine** (`aion/`) and the **design documentation** (`Docs/`). Each document owns one concern — *one fact, one home* — so they stay consistent as the project evolves.

> **Scope:** v0 targets **C++**. Multi-language support (Python → Rust / Java / Go / JS) is **Axis A** (`AION.md` §12) — planned and architected for, not yet built.

## Quickstart

Runs on your system Python (3.8+), no install needed. Requires `clang++` and `g++` (the sanitizer fallback).

```bash
cd "…/AI_Optimizer_Network - (AION)"
export PYTHONPATH="$PWD"

# Optimize the example — really compiles, differential-tests, runs ASan/UBSan, benchmarks:
python3 -m aion.surfaces.cli optimize examples/packet_stats.cpp --offline
```

Expected (takes ~6s — it's actually building + benchmarking):

```
  reserve_before_pushback  →  ACCEPT
    correctness: Rung 3 (clean)
    performance: p50 2.22 ms (-68.0%)  pareto=True
```

Other commands:

```bash
python3 -m aion.surfaces.cli analyze examples/packet_stats.cpp --offline           # non-destructive
python3 -m aion.surfaces.cli analyze examples/packet_stats.cpp --offline --json     # machine output
python3 -m aion.surfaces.cli report                                                 # read the Ledger
```

Notes:
- **`--offline`** uses the deterministic rule proposer (no LLM/API key). The frontier LLM proposer isn't wired yet — `--model frontier` errors cleanly telling you to use `--offline`.
- On Python 3.11+, `pip install -e .` installs a plain `aion` command (declared in `pyproject.toml`).

## Development setup (Python 3.11 venv)

Optional — AION runs on system Python 3.8 (see Quickstart). Python 3.11+ enables the packaged `aion` command and `tomllib` config loading.

> ⚠️ Do **not** replace the system `python3` on Ubuntu 20.04 — install 3.11 *alongside* it.

**Install 3.11 (deadsnakes PPA):**

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.11 python3.11-venv python3.11-dev
```

**Create the venv and install AION:**

```bash
cd "…/AI_Optimizer_Network - (AION)"
python3.11 -m venv .venv
source .venv/bin/activate         # `python` / `pip` are now 3.11
pip install -e '.[dev]'           # installs the `aion` command + pytest
aion optimize examples/packet_stats.cpp --offline
pytest -q                         # run the tests
```

No-sudo alternative with [`uv`](https://astral.sh/uv):

```bash
uv python install 3.11
uv venv --python 3.11 && source .venv/bin/activate
uv pip install -e '.[dev]'
```

## Repository layout

```
README.md            ← you are here
Docs/                ← design documentation (.md + .html twins)
aion/                ← the v0 engine (Python)
  engine/            gate · orchestrator · ports · models · ledger · registry · api
  adapters/          language/cpp · domain/performance · model · transforms
  runtime/           sandbox · bench_runner
  surfaces/          cli
examples/            packet_stats.cpp  (the canonical reserve() case)
tests/               gate invariant tests
```

## Documents

| Document | Owns | Read it for |
|---|---|---|
| **[AION.md](Docs/AION.md)** · [html](Docs/AION.html) | The **design spec** — what AION is, why it's needed, where it sits in compilation, the invariant, the four-stage loop, the seven axes, prior art. | Understanding the idea and why it's sound. |
| **[AION_Surfaces.md](Docs/AION_Surfaces.md)** · [html](Docs/AION_Surfaces.html) | The **surface specs** — how AION is delivered (CLI, CI action, IDE extension, dashboard, network, SDK), staged v0→vision. | What the user actually runs. |
| **[WEDGE_TEST.md](Docs/WEDGE_TEST.md)** · [html](Docs/WEDGE_TEST.html) | The **pre-registered benchmark** — head-to-head vs Codeflash / CompilerGPT, the cases, the judge, honest predictions. | Proving (or disproving) AION's differentiation. |
| **[AION_Architecture.md](Docs/AION_Architecture.md)** · [html](Docs/AION_Architecture.html) | The **engineering blueprint** — the language-agnostic engine core, abstract adapter contracts, multi-language support (universal vs per-language, the support matrix), **and the concrete C++ instance (v0)** inline in §16. | Understanding *and* building the engine. |

Every `.md` has a styled, self-contained `.html` twin (sidebar nav, light/dark) for reading in a browser.

## The idea in one line

The core loop (LLM proposes → verify correct → verify faster → accept) is **not novel** — Codeflash ships it, Google's ECO runs it, CompilerGPT does it for C++. AION's bet is **integration, not invention**: formal rigor (contracts + a graded correctness ladder) as the spine, for **C++ systems code**, with profile-guided selection and a verified-transform network. That bet is defensible but unproven — which is what the [Wedge Test](Docs/WEDGE_TEST.md) exists to settle.

## Status

**v0 in progress — the trusted gate is real and working.** On `examples/packet_stats.cpp`, `aion optimize` genuinely compiles, differential-tests, runs ASan/UBSan, and benchmarks — accepting `reserve()` with a **real measured −68%** at correctness Rung 3. The differentiator is proven too: a UB rewrite that *passes* the differential test is **rejected** because AddressSanitizer catches it (`REJECT unsafe`).

- ✅ Engine core (gate · orchestrator · ports · ledger · registry) + gate-invariant tests
- ✅ Real correctness oracle (differential test + ASan/UBSan ladder) and performance oracle (Pareto vector)
- ✅ Light-real C++ sensor/mutator (regex) + the `reserve()` transform
- ⬜ **Next:** libclang AST sensor/mutator (robust) · frontier LLM proposer · more transforms · wire the Wedge Test

## Where each concern lives (so nothing gets duplicated)

- **Concepts / why** → `AION.md`
- **How it's built** → `AION_Architecture` (generic engine + the C++ v0 instance in §16; splits into per-language docs when a 2nd language lands)
- **How it's delivered** → `AION_Surfaces`
- **How it's proven** → `WEDGE_TEST`
