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

Files already ≤150 LOC and cohesive — **don't split or move them**: everything in `engine/` (models, ports, config, ledger, gate, orchestrator, registry, api, apply_txn), plus `link.py`, `profile.py`, `reuse.py`, `performance.py`, `compile_db.py`, `sensor.py`, `runtime/*`. Splitting a 154-line file into two 77-line files is churn without benefit.

("Don't split or move" is about *structure* — a couple of these still get *internal* edits from later steps: `sensor.py` goes generic in §7 and `_verify.py` gains `BuildSpec` in §6. That's fine; the point is their size and location are already right.)

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

Two moves at once: **split the six oversized files by concern**, and **relocate two things that are mis-placed today** — so `adapters/` ends up as three clean axes (a language plugin, a domain plugin, a proposer).

```
adapters/language/cpp/                ← the C++ language plugin
  analysis/                 ← was _ast.py (424) — 4 concerns
    parse.py                  libclang TU parse, thread-local flags, diagnostics
    types.py                  signature, _clean_type, aggregate_fields
    detect.py                 growth / map / string site detection
    safety.py                 side-effects + templates (items 1c / 1d)
  build/                    ← was build.py (188)
    compile.py                compile_program + executable cache
    toolchain.py              ccache, fast-linker, sanitizer / TSan / MSan probes
  transforms/               ← MOVED from adapters/transforms/ (see note below)
    reserve.py                reserve-vector + reserve-string, merged onto a base
    map_to_unordered.py
    base.py  registry.py
  regex_detect.py           ← was _detect.py — regex fallback + AST-preferring wrappers
  compile_db.py  link.py  profile.py  profiler.py  mutator.py
  sensor.py                 (kept; internals go generic in §7)

adapters/domain/performance/          ← the performance-domain plugin
  correctness.py            ← slim: the oracle + equivalent() orchestration only
  sanitizers.py             ← extracted: ASan/TSan build+run, diagnostic markers
  compare.py                ← extracted: _outputs_match (1b), _first_diff
  harness/                  ← was harness_gen.py (212)
    template.py               the C++ harness text (check/race/bench) + assembly
    synth.py                  input synthesis (classify / builder / serialize)
  performance.py  inputs.py  reuse.py
  _verify.py                (kept; gains BuildSpec in §6)

adapters/proposer/                    ← RENAMED from model/  (it IS the PROPOSE axis)
  rules.py  frontier.py

surfaces/cli/               ← was cli.py (580)
  main.py                     entry point + dispatch
  parser.py                   argparse construction + HelpFormatter + cheatsheet
  config_build.py             _build_config (args → Config)
  render.py                   human / json / codebase output + export
```

**Why `transforms/` moves under `language/cpp/`.** Every concrete transform already imports `language.cpp._detect` (`reserve_*`, `map_to_unordered`) — they are part of the C++ plugin, not a cross-cutting adapter. Only the universal `Transform`/`Contract` ABC (`base.py`) is language-agnostic; it rides along for now (YAGNI — *all* transforms are C++ until a 2nd language lands, at which point `base` lifts up). This also puts each transform **next to the detection it uses**, which is exactly what §7 wants.

**Why `model/` → `proposer/`.** "model" is ambiguous (ML model? data model?); the directory holds `rules.py` + `frontier.py` — the **proposer**. The rename matches the VERIFY/**PROPOSE** vocabulary used everywhere else.

**Result:** `adapters/` = `{ language/cpp , domain/performance , proposer }` — three adapters, one per architectural axis, with no stray `transforms/` muddying the picture.

**Naming decision:** the AST subpackage is `analysis/`, **not** `ast/` — `ast` shadows Python's standard library. Subpackages (`analysis/`, `build/`, `harness/`, `cli/`, `transforms/`) are preferred over flat prefixed files (`ast_parse.py`) because the grouping is itself documentation.

---

## 6. Deduplicate & consolidate — not just split

Splitting (§4–5) fixes file *size*. It does nothing for *repetition* or *scattered state* — and organizing code means both. This axis is often higher-value than splitting: **duplication is where the next bug lands** (a fix has to be made in N places), and scattered config is what makes code hard to follow. Four concrete targets, with counts from the current tree:

1. **Extract duplicated helpers.**
   - The **thread-unique temp-name** pattern `f"{x}.{getpid()}.{get_ident()}.tmp"` is copy-pasted **4×** (`apply_txn.py`, `link.py` ×2, `build.py`). → one `_unique_tmp(path)` helper.
   - `_detect.py` has **12 identical shim wrappers** — every one is `try: from ._ast import X; return X(...) except: return <fallback>`. → one generic "prefer-AST, fall back to regex" dispatcher instead of twelve copies.

2. **Consolidate the build-config.** `VerifyCtx` threads `extra_cflags` / `link_inputs` / `opt_flags` as **3 parallel tuple fields**, read via defensive `getattr(ctx, …)` at **5 sites**. They are one concept — *how to build this TU in codebase mode* — and want to be a single **`BuildSpec`** value passed around whole (which also deletes the `getattr` noise).

3. **Un-sprawl `Config`.** It's **20 flat fields** mixing four concerns — gate policy (`min_rung`, `objectives`, `allow_regression`), benchmarking (`reps`, `adaptive`, `min_speedup_pct`), evidence (`profile`, `fuzz_inputs`, `seed`), proposal (`model`, `transforms`), and test-reuse (`test_command`, `test_dir`, `test_timeout_sec`). Group into sub-configs (or at least clearly section them).

4. **Consolidate the existing transforms.** `reserve_before_pushback` and `reserve_string` are both "insert a `reserve()`" transforms sharing most of their logic. Fold them onto a shared base **as part of §7's redesign** — not as a separate cleanup afterward.

*The split axis (§4–5) fixes size; this axis fixes duplication + cohesion. Do both, or "organized" is only half true.*

---

## 7. The payoff refactor — make transforms self-contained ✅ **done**

This was *design*, not just moving files, and it's the one that pays for itself when we add the next 8–10 transforms.

**Before, adding one transform touched ~8 places:** an example `.cpp`, a detector, a `_detect` wrapper, the transform class, `transforms/__init__.ALL`, a hand-built `Fact` in `sensor.py`, harness support, and a wedge case.

**Key finding that made it clean:** the rule proposer never read `ev.facts` (it uses `target.symbol` + iterates transforms calling `matches()`), and `check_precondition` uses the source, not facts — so **the sensor's hardcoded per-type `Fact`-building was dead code.** Shipped:
- **`Transform.candidates(source) → list[str]`** — each transform declares which functions it matches (`_ReserveBase` via `_all_sites`, `MapToUnorderedMap` via `detect_all_map`).
- **A generic `sensor.py`** — candidate functions are the **union of `t.candidates(source)` over `ALL`**; the hardcoded growth/map/string detection and *all* Fact-building are gone. Skip-logging and profile-selection stay.

**Result: adding a transform is now ~1 new file** (the transform class + register in `ALL`) plus an example and a wedge case — **the sensor is untouched.**

---

## 8. Sequencing — small, test-verified steps (never a big-bang)

Every step is validated by the full suite (**45 tests + wedge 11/11**) before the next. No step changes behavior except where explicitly noted.

1. **Dead-code delete** ✅ — removed `Config.candidates` / `sandbox` / `timeout_sec` (zero readers) and `orchestrator._write_patch` (superseded by `ApplyTransaction`; the write path always has a `txn`).
2. **Split & relocate** ✅ — split the 6 files **and** relocated the two mis-placed things (`transforms/` → `language/cpp/`, `model/` → `proposer/`) into the §5 tree.
3. **Deduplicate & consolidate** ✅ *(core)* — extracted the temp-name helper (`runtime/fs.unique_tmp`) and the `regex_detect._ast_only` dispatcher. *`BuildSpec` and `Config` sub-config grouping deferred — moderate value, high churn on the trusted verify path.*
4. **Slim the gate** ✅ — `correctness.py` 170→~85 LOC; extracted `sanitizers.py` (ASan/TSan build+evaluate) and `compare.py` (`_outputs_match`/`_first_diff`).
5. **Transform ergonomics** ✅ — merged the two `reserve` transforms onto `_ReserveBase`, and made the sensor generic via `Transform.candidates()` (§7).

Every step was verified against the full suite (**45 pass + 1 skip, wedge 11/11**) before the next; the tree was never broken. *Deferred (optional): `BuildSpec` + `Config` grouping.*

---

## 9. Open decisions

- **Subpackages vs flat prefixed files** — this plan uses subpackages (`analysis/parse.py`); the alternative is flat (`ast_parse.py`). Subpackages chosen for clarity.
- **Reason strings → enum?** `verdict.reason` / `skip.reason` are free strings (`"tests_failed"`, `"changed_output"`…). An enum would make handling exhaustive/checkable but touches many call sites — **deferred** (tidiness, not leverage) unless it starts causing bugs.
- **POC-vs-production split** — separating stub/experimental code (`frontier.py`, the regex fallbacks) into a marked area was considered and **deferred**: those parts are small and clearly commented; a formal split adds structure this small codebase doesn't need yet.
