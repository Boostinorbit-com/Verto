# Tests

Two independent axes. **Folders = which layer**, **markers = what it costs.** They're separate
because cost doesn't respect layer: `engine/test_cache.py` holds a 25s compile-and-benchmark
test *and* four millisecond ones, so no folder split can give you a fast subset.

## Folders — mirror `boostopt/`

| Folder | Covers |
|---|---|
| `engine/` | the gate, orchestrator, and persistent state (ledger, cache, baselines, workspace) |
| `adapters/transforms/` | one module per C++ transform: detector → end-to-end verdict |
| `adapters/cpp/` | the C++ language adapter — build flags, cross-TU link, profile, ctest discovery |
| `adapters/oracles/` | correctness oracles — fuzzed inputs, capture/replay, test-reuse, metamorphic |
| `adapters/proposer/` | the LLM proposer (mechanism tests are offline; live ones are opt-in) |
| `runtime/` | cost budget, sandbox isolation, local-model provisioning |
| `surfaces/` | CLI render, patch export, GitHub Action bridge |
| `premium/` | `boostopt_server` — the proprietary hosted tier |
| `invariants/` | repo-wide rules tested rather than trusted (the open-core boundary) |

Every folder is a package (`__init__.py`) — that's how `check.sh` can do
`import tests.engine.test_gate`. Add one when you add a folder.

Filenames say what is tested, not which roadmap item asked for it: the old `test_2a1_*`,
`test_2a_*`, `test_2c_*`, `test_2d_*` names are now `test_ctest_discovery`, `test_oracle_reach`,
`test_patch_series`, `test_metamorphic`. The roadmap codes still open each module's docstring
(`"""2A-1 — CMake/ctest test-target discovery…"""`), so traceability to `Docs/BOOSTOPT_Roadmap.md`
survives without the code being the thing you grep for.

## Markers — declared in `pyproject.toml`

```bash
pytest -m "not toolchain"    # the inner loop: no clang++, seconds
pytest tests/adapters/transforms   # did I break a transform?
pytest -m premium            # the paywall layer only
pytest                       # everything (~4.5 min; really compiles and benchmarks)
```

- **`toolchain`** — drives real clang++/g++. Measured at ≥0.5s; the slowest is ~44s. 43 tests
  carry it and they are ~95% of the wall clock.
- **`bench`** — a benchmark decides pass/fail, so it can flake under CPU contention. This is what
  CI's `--reruns 2` exists for.
- **`live`** — needs a running Ollama with the local model; opt in with `BOOSTOPT_LIVE_LLM=1`.
- **`premium`** — exercises `boostopt_server`, which never ships in the public wheel.

Mark a new test `toolchain` if it constructs an `Engine` and optimizes a real file. When in
doubt, run `pytest --durations=10` — anything that shows up there belongs behind the marker.

## Shared paths

Never spell the repo root as `Path(__file__).parent.parent` — that silently resolved to `tests/`
when these files moved into subfolders. Import the constants instead:

```python
from tests import REPO_ROOT, EXAMPLES, LINKED, FIXTURES
```

They're derived by walking up to `pyproject.toml`, so they survive the next reshuffle.

## Gotchas

- `invariants/test_boundary.py` imports `setuptools`, which the project `.venv` doesn't have.
  Run it from an environment that does, or `pytest --ignore=tests/invariants` locally.
- `conftest.py` stays at `tests/` root — its autouse hermeticity fixture (isolating
  `$XDG_CONFIG_HOME` and the rewrite cache) inherits into every subfolder automatically.
