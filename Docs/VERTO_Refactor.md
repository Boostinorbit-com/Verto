# VERTO — Refactoring Plan

**How to reshape the codebase after Phase 1: organize by concern, split the few oversized files, and make adding a transform cheap — without over-refactoring a small, healthy codebase.**

Companion to `VERTO_Roadmap.md` (what to build) and `VERTO_Architecture.md` (the blueprint this must respect).

---

## 1. Why now, and the goals

Phase 1 landed 9+ features fast (link-against-build, test-reuse, skip-log, real-profile, real-flags, aggregate-synthesis, fuzzing, scale, safe-apply, plus the 1a–1d completeness batch). The core held up — but some files now bundle several concerns, and the next real work is **transform coverage** (adding 8–10 more transforms). This plan tidies the codebase *for that*.

Three goals, in priority order:
1. **Organize by concern** — feature-specific code (sanitizers, FP-tolerance, TSan) is currently bundled into large multi-purpose files; separate it.
2. **~100–150 LOC per file** — as a *natural result* of goal 1 (see the principle below), not a target to chop toward.
3. **Make "add a transform" cheap** — today it touches ~8 places; collapse that to ~1–2.

---

## 2. The guiding principle (read this first)

**Split by cohesion — one concern per file. The line count follows; it is not the target.**

Mechanically chopping a cohesive 160-line class into two 80-line halves *hurts*: you get artificial coupling and more files to hop between. Conversely, a file with a big embedded C++ harness template sitting at 170 lines is fine — it's one concern.

So the rule is: **a 300-line file doing four unrelated things must split; a 160-line file doing one thing well should not.** 100–150 is the healthy range you land in when each file has a single job — treat it as a smell threshold, not a hard cap.

---

## 3. What's already healthy — do NOT touch

The codebase is **~3,380 LOC total, with no monster files** (biggest is `cli.py` at 580). This is tidying, not a rescue. The **ports/adapters architecture survived 9 features without bending** — the gate is still the single `accepted=True`, the VERIFY/PROPOSE split stayed clean. Keep it.

Files already ≤150 LOC and cohesive — leave them: everything in `engine/` (models, ports, config, ledger, gate, orchestrator, registry, api, apply_txn), plus `link.py`, `profile.py`, `reuse.py`, `performance.py`, `compile_db.py`, `sensor.py`, `runtime/*`. Splitting a 154-line file into two 77-line files is churn without benefit.

`tools/gen_flags.py` is already correctly separated as dev-tooling — no change.

---

## 4. The files that actually need splitting (6 of them)

Only six files exceed the threshold *and* bundle multiple concerns:

| File | LOC | Concerns bundled together |
|---|---|---|
| `surfaces/cli.py` | 580 | parser build · config wiring · output rendering · help/cheatsheet · dispatch |
| `language/cpp/_ast.py` | 424 | libclang parse infra · type analysis · site detection · safety checks (1c/1d) |
| `domain/performance/harness_gen.py` | 212 | the C++ harness template · input synthesis |
| `language/cpp/_detect.py` | 194 | regex fallback detectors · the AST-preferring wrappers |
| `language/cpp/build.py` | 188 | compile + exe-cache · toolchain probes (ccache/linker/sanitizers) |
| `domain/performance/correctness.py` | 170 | diff-test · sanitizers (ASan/TSan) · FP-tolerance · the rung ladder |

---

## 5. Proposed directory structure

Split the six by concern; group tightly-related modules into subpackages.

```
adapters/language/cpp/
  analysis/                 ← was _ast.py (424) — 4 concerns
    parse.py                  libclang TU parse, thread-local flags, diagnostics
    types.py                  signature, _clean_type, aggregate_fields
    detect.py                 growth / map / string site detection
    safety.py                 side-effects + templates (items 1c / 1d)
  build/                    ← was build.py (188)
    compile.py                compile_program + executable cache
    toolchain.py              ccache, fast-linker, sanitizer / TSan / MSan probes
  regex_detect.py           ← was _detect.py — regex fallback + AST-preferring wrappers
  compile_db.py  link.py  profile.py  profiler.py  sensor.py  mutator.py   (unchanged)

adapters/domain/performance/
  correctness.py            ← slim: the oracle + equivalent() orchestration only
  sanitizers.py             ← extracted: ASan/TSan build+run, diagnostic markers
  compare.py                ← extracted: _outputs_match (1b), _first_diff
  harness/                  ← was harness_gen.py (212)
    template.py               the C++ harness text (check/race/bench) + assembly
    synth.py                  input synthesis (classify / builder / serialize)
  performance.py  inputs.py  _verify.py  reuse.py   (unchanged)

surfaces/cli/               ← was cli.py (580)
  main.py                     entry point + dispatch
  parser.py                   argparse construction + HelpFormatter + cheatsheet
  config_build.py             _build_config (args → Config)
  render.py                   human / json / codebase output + export
```

**Naming decision:** the AST subpackage is `analysis/`, **not** `ast/` — `ast` shadows Python's standard library. Subpackages (`analysis/`, `build/`, `harness/`, `cli/`) are preferred over flat prefixed files (`ast_parse.py`) because the grouping is itself documentation.

---

## 6. The payoff refactor — make transforms self-contained

This is *design*, not just moving files, and it's the one that pays for itself when we add the next 8–10 transforms.

**Today, adding one transform touches ~8 places:** an example `.cpp`, an `_ast` detector, a `_detect` wrapper, the transform class, `transforms/__init__.ALL`, a hand-built `Fact` in `sensor.py`, harness support, and a wedge case.

**Target:** a `transforms/<name>.py` that **declares its own** detector + precondition + rewrite + harness-needs in one place, and a **generic `sensor.py`** that iterates the registered transforms and asks each "do you match here?" — instead of hand-coding growth/map/string detection and Fact-building. Adding a transform becomes ~1 new file (+ an example + a wedge case).

This lands *after* the file splits (§5), because the split gives it a clean home (`analysis/detect.py`, `transforms/`).

---

## 7. Sequencing — small, test-verified steps (never a big-bang)

Every step is validated by the full suite (**45 tests + wedge 11/11**) before the next. No step changes behavior except where explicitly noted.

1. **Dead-code delete** *(free, ~10 min)* — remove `Config.candidates` / `sandbox` / `timeout_sec` (zero readers) and `orchestrator._write_patch` (superseded by `ApplyTransaction`; the main flow always passes a `txn`).
2. **Split the 6 files** *(mechanical, behavior-identical)* — moves + import updates into the §5 tree. Reviewable as pure reorganization.
3. **Slim the gate** — the `correctness.py` → `sanitizers.py` + `compare.py` extraction; the trusted core reads as a clean ladder.
4. **Transform ergonomics** *(the design work, §6)* — self-contained transforms + generic sensor.

Steps 1–2 are low-risk and give most of the readability win; 3–4 are where the design judgment lives. Recommend pausing for review after step 2.

---

## 8. Open decisions

- **Subpackages vs flat prefixed files** — this plan uses subpackages (`analysis/parse.py`); the alternative is flat (`ast_parse.py`). Subpackages chosen for clarity.
- **Reason strings → enum?** `verdict.reason` / `skip.reason` are free strings (`"tests_failed"`, `"changed_output"`…). An enum would make handling exhaustive/checkable but touches many call sites — **deferred** (tidiness, not leverage) unless it starts causing bugs.
- **POC-vs-production split** — separating stub/experimental code (`frontier.py`, the regex fallbacks) into a marked area was considered and **deferred**: those parts are small and clearly commented; a formal split adds structure this small codebase doesn't need yet.
