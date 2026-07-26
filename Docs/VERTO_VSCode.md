# VERTO for VS Code — the editor extension, explained from scratch

**This document is the design note for VERTO's VS Code extension (a `v1` surface): what it is, what makes it unlike any other editor plugin, and exactly how it's built on top of what VERTO already has.** It assumes no prior VS Code-extension knowledge — every term is defined the first time it appears.

---

## 1. The one sentence that defines it

Every other AI/optimizer plugin shows you a **suggestion you then have to vet.** VERTO shows you a **verdict with its proof attached.**

> **Other extensions autocomplete guesses. VERTO surfaces *verified* wins — with the proof one hover away, and an Apply button you can actually trust.**

That single difference — *proof, not a guess* — drives every design choice below.

**A note on what is *not* the differentiator.** The editor *widget* — a CodeLens above a function, run on demand, applied inline — is common to verified-optimizer tools; expect it to look familiar. VERTO's edge is **substance, not shape**, on three axes: it **shows the proof** (the evidence, not just the rewrite — §8), it verifies **deeper** (C++ with sanitizers + fuzzed differential testing, not just regression tests), and it can run **fully local** (a local model, no sign-in, code never leaves the box — §10). Compete on those, not on the CodeLens.

---

## 2. The idea in one picture

```
   You're editing hot_loop.cpp in VS Code
            │
            ▼
   ⚡ VERTO — optimize this function            ← a CodeLens above the function
            │  (click it — the gate runs in the background, a few seconds)
            ▼
   ⚡ VERTO — verified −52%  ✓                   ← the CodeLens resolves when PROVEN
            │  (hover it)
            ▼
   ┌──────────────────────────────────────────────┐
   │ Proven behavior-identical:                     │
   │   • byte-identical on 1,010 fuzzed inputs      │
   │   • ASan / UBSan / TSan clean (Rung 3)         │
   │ Measured: p50 −52%  (10.06 ms → 4.85 ms)       │
   │            [ Apply ]   [ Show diff ]           │
   └──────────────────────────────────────────────┘
            │  (click Apply)
            ▼
   The verified change is written to your file — no careful review needed,
   because it was PROVEN correct-and-faster before Apply was ever offered.
```

The CodeLens starts as an *invitation* (proving takes seconds — see §6), not a passive claim. What's unique isn't that widget; it's that when it resolves, **the suggestion carries its evidence**, and Apply is safe because the change was proven *before* it was offered.

---

## 3. The words you need (each defined once)

- **Extension** — a plug-in that adds features to VS Code. Written in TypeScript/JavaScript, it runs in a sandboxed "extension host" process alongside the editor.
- **CodeLens** — a small, clickable line of text VS Code renders **above a line of code** (e.g. above a function). Perfect for *"⚡ VERTO — optimize this function"* → (after the async run) *"verified −52% ✓."*
- **Hover** — the tooltip that appears when you rest the mouse over code. We use it to show the **proof**.
- **Code action** (a.k.a. the 💡 "Quick Fix" lightbulb) — an action offered for a bit of code, e.g. *"VERTO: verify & optimize this function."* Triggered on right-click or `Ctrl+.`.
- **Diagnostic** — an entry in the **Problems panel** (the things linters put squiggles under). VERTO uses an *informational* diagnostic: *"verified optimization available."*
- **WorkspaceEdit** — the VS Code API for **changing files programmatically.** "Apply" turns VERTO's verified diff into a `WorkspaceEdit`.
- **Extension host / daemon** — the extension talks to a long-running **VERTO daemon** (a warm `verto` process) so repeated requests skip startup cost.
- **`compile_commands.json`** — the **compilation database**: the exact flags each file is built with. VERTO needs it to parse and build a file the way the real project does. (CMake: `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`.)
- **`Verdict`** — VERTO's core result object (transform, correctness rung + witness, performance vector, diff). **Every VERTO surface renders the *same* `Verdict` JSON** — the extension is just one more renderer of it.

---

## 4. The core principle: a verdict, not a suggestion

Hold onto the distinction, because it's the whole product:

| | A typical AI plugin | VERTO |
|---|---|---|
| What it shows | a plausible rewrite | a rewrite **already proven** behavior-identical + faster |
| Your job after | read it, test it, hope | glance at the proof, click Apply |
| If it's unsure | shows it anyway | **says nothing** (or says *why* it can't verify) |
| Trust model | "review carefully" | "it was verified before you saw it" |

Everything the extension renders is a `Verdict` that already **passed the gate**. There is no "unverified suggestion" state — that's the point.

---

## 5. The five surfaces in the editor

1. **The CodeLens — an invitation that becomes a verdict.** Above a function it starts as `⚡ VERTO — optimize this function`; clicking runs the gate in the background, and when proven it resolves to `⚡ VERTO — verified −52% ✓`. *(The CodeLens shape is common to optimizer tools — that's fine; what's VERTO is that it resolves to a **proven** result, never an accepted guess.)*
2. **Proof-on-hover** *(the real differentiator)* — hovering the finding shows the **actual evidence**, not a pitch:
   > *byte-identical on 1,010 fuzzed inputs · ASan/UBSan/TSan clean (Rung 3) · p50 −52% (10.06 ms → 4.85 ms, on this machine).*
   Competing tools verify under the hood but foreground only the *suggestion*; VERTO foregrounds the *proof*. This — not the widget — is the signature move.
3. **Safe Apply** — because the change is pre-verified, the Apply button is trustworthy: one click, no anxious review. Applied via `WorkspaceEdit` from VERTO's own diff.
4. **Async "verify & optimize" code action** — right-click a function → VERTO runs the **gate in the background** (progress in the status bar) and streams the verified result when done. It never blocks typing and never shows an unproven guess.
5. **Honest silence** — if VERTO *can't* verify a function (e.g. a signature it can't synthesize inputs for), it says so plainly (`can't synthesize inputs for this signature`) instead of staying quiet or guessing. Transparency is a feature.

Those five are the *baseline* UX — and they look like other tools. For the features that **only a verifying extension can offer** (catching bugs for free, proof-as-a-show, the verifiability map…), see **§13**.

---

## 6. The latency reality — a "verified code action," not a linter

This is the single most important design constraint, and getting it right is what separates a delightful extension from a broken-feeling one.

**VERTO's gate is slow by nature** — compile + differential-test + sanitizers + benchmark is *seconds to minutes per function*. A linter squiggles as you type; **VERTO cannot and must not pretend to.** So the mental model is:

> **VERTO in the editor is a *slow, trustworthy test-runner*, not a real-time linter.**

Concretely:
- **Nothing runs on keystroke.** Verification is **on-demand** (the code action) or **on-save in the background**, your choice.
- Results **stream in asynchronously** — a status-bar spinner while it works, the CodeLens/diagnostic appears when the verdict is ready.
- Typing is **never blocked**, and a stale finding is cleared the moment the code under it changes.

Faking real-time here would over-promise and feel broken. Owning the latency honestly ("verifying… ✓ proven −52%") feels *trustworthy* — which is on-brand.

---

## 7. How it reuses what's already built (it's a thin client)

The extension is **not a rewrite of anything.** VERTO already has the two pieces it needs:

- **`verto optimize <file> --json`** already emits the `Verdict` payload the extension renders.
- The **daemon** (a warm `verto` process) already exists so repeated calls are fast.

So the extension is a modest TypeScript project that:
1. finds the project's `compile_commands.json` + `.verto.toml`,
2. calls the daemon: `optimize(file) → Verdict[]` (as `--json`),
3. renders each `Verdict` as a CodeLens + hover + Problems entry,
4. on Apply, turns the verdict's diff into a `WorkspaceEdit`.

**The same `Verdict` that becomes a CLI table row and a PR comment becomes an editor hint** — one payload, three renderers. That's why this surface is cheap to build and impossible to drift from the CLI's behavior.

---

## 8. The trust triplet, in a tooltip

VERTO's "why-safe / why-faster / measured" triplet — the same one in the PR comment — is what the hover shows. A concrete mock:

```
VERTO — reserve() before the loop

  Why it's safe   byte-identical output on 1,010 fuzzed inputs;
                  ASan · UBSan · TSan clean (Rung 3)
  Why it's faster avoids ~10 vector reallocations the compiler
                  can't elide (it can't prove the final size)
  Measured        p50 −52%  (10.06 ms → 4.85 ms) · peak-mem ±0%
                  (on this machine; larger on production hardware)

  [ Apply ]   [ Show diff ]   [ Why skipped others? ]
```

The correctness lines are stated as **fact** (toolchain-independent). The speed-up carries the honest **"on this machine"** caveat. That honesty *is* the brand — even in a tooltip.

---

## 9. The architecture, in plain words

```
  VS Code  ──(extension host, TypeScript)──►  VERTO extension
                                                   │
                                    optimize(file), as --json over a socket
                                                   ▼
                                         VERTO daemon (warm `verto`)
                                                   │
                                          the same Engine + trusted gate
                                          the CLI and CI Action already use
```

- The extension holds **no engine logic** — it's a renderer + an RPC client.
- It reads `.verto.toml`, so **the editor and the CLI behave identically** (same rungs, transforms, profile).
- Everything runs **locally** — your code never leaves the machine.

---

## 10. Free vs paid

**Free.** The extension runs on the user's machine over the local CLI/daemon — squarely the *"everything on your side is free"* tier (same logic as the self-run CI Action). Paid hooks appear only if it reaches VERTO's **hosted** services — e.g. routing the benchmark to a **clean room** for numbers steadier than a busy laptop, or a **managed model** — authenticated with `verto-token`. The gate, the CodeLens, the proof, the Apply: all free.

---

## 11. Design principles (and the anti-patterns to avoid)

**Do**
- Show **only verified findings** — there is no "unverified suggestion" state.
- Put the **proof one hover away** — evidence, not adjectives.
- Be **honest about latency** — spinner while verifying, result when ready.
- **Disclose skips** — say *why* a function couldn't be verified.

**Don't**
- ❌ Run the gate on keystroke, or fake real-time verification.
- ❌ Show a guess you haven't proven (that's every other tool; it's not VERTO).
- ❌ Inflate the number — keep the *"on this machine"* caveat.
- ❌ Duplicate engine logic in TypeScript — always go through the daemon, so behavior can't drift from the CLI.

---

## 12. Status & the smallest first version

**MVP built & confirmed working in the editor (2026-07-27)** — lives in [`editors/vscode/`](../editors/vscode/). Installed from a `.vsix` and run on a real C++ file: the command → *verifying…* → ⚡ CodeLens → proof-on-hover → Apply all work. The deliberately-small first version:

1. A **command** — "VERTO: Verify & Optimize Current File" — spawns `verto … --json` and collects the findings. ✅
2. **CodeLens + proof-on-hover** rendering of each `Verdict`. ✅
3. **Apply** via `WorkspaceEdit` (from the verdict's `udiff`). ✅

Pure logic (`src/core.ts`: parse `--json`, diff→edits, proof markdown) is **unit-tested off the editor** (8 tests green); the extension **type-checks against `@types/vscode`** and **packages to a `.vsix`**. End-to-end verified without the editor: real `verto --json` → parse → anchor/label/apply. *What's left is the in-editor UX itself (CodeLens/hover/Apply pixels) — that needs VS Code running, plus CodeLens polish, on-save mode, and the "why skipped" view.* A few hundred lines of TypeScript, because the hard parts (the gate, `--json`, the daemon) already existed.

---

## 13. Five features only a *verifying* extension can offer

The surfaces in §5 (CodeLens, hover, Apply) look like other tools — that's expected. These five don't, because each one is only possible when the extension **actually runs and proves your code.** A suggestion-based plugin structurally cannot copy them.

**1. Catch bugs for free while optimizing.**
While VERTO runs your code to check an optimization, it's also running memory-safety detectors (ASan/UBSan/TSan). So sometimes it finds a *bug* even when there's no speed-up.
- *You'd see:* `⚠️ No faster version found — but VERTO caught a data race on line 14 while verifying.`
- *Only VERTO:* other plugins never execute your code, so they can't catch a real bug. VERTO already runs it — bug-catching is almost free.

**2. Turn the wait into a show of proof.**
Verifying takes a few seconds; instead of a blank spinner, stream *what it's doing.*
- *You'd see:* `compiling… → 1,010 inputs identical ✓ → ASan · UBSan · TSan clean ✓ → measuring… −52%.`
- *Only VERTO:* others are just asking a model — nothing to show. VERTO is doing real checks, so it can let you *watch the proof happen.* The latency becomes the selling point.

**3. A verifiability heat-map of the file.**
Color every function by VERTO's honest status, in the gutter.
- *You'd see:* 🟢 *proven win available* · ⚪ *already optimal* · 🟡 *can't verify (why: unharnessable signature)*.
- *Only VERTO:* it's honest about where it *can't* help, not just where it can — a truthful map no guess-based tool can draw.

**4. "Why your compiler didn't already do this."**
Explain, per finding, the limit VERTO got past that `-O3` couldn't.
- *You'd see:* `-O3 couldn't pre-reserve() here — it can't prove the final size. VERTO checked, and it's safe.`
- *Only VERTO:* it works *above* the compiler and *proves* the transform safe, so it can honestly claim the wins the compiler left behind.

**5. Protect a win you already earned (the contract, live).**
If VERTO proved a function fast and you later edit it, it warns you before you undo the win.
- *You'd see:* `🔒 You're editing a function VERTO already sped up — re-verify before committing?`
- *Only VERTO:* it remembers what it *proved* fast, so it can notice regressions at authoring time. A guess has no proven baseline to protect.

> **The through-line:** all five fall out of one fact — VERTO *runs and proves* your code. That's the moat translated into the editor, not the CodeLens.

---

## 14. Quick answers

- **Will it slow down my editor?** No — nothing runs on keystroke; verification is on-demand/background and never blocks typing.
- **Does my code leave my machine?** No — it runs the local daemon. (Only opt-in hosted features would, and those are separate + paid.)
- **Why not instant like a linter?** Because *proving* a change (compile + test + sanitize + benchmark) takes seconds — and a real proof is worth the wait. VERTO owns that honestly.
- **Do I need `compile_commands.json`?** Yes — so VERTO builds each file exactly as your project does (CMake: `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`).
- **How is this different from an AI autocomplete?** Autocomplete guesses and asks you to review. VERTO only ever shows changes it has **already proven** correct-and-faster.

---

*Companion docs: `VERTO_Surfaces` (all surfaces + the shared `Verdict` payload), `VERTO_CI_Action` (the PR-comment surface — same trust triplet, different renderer), `VERTO_Roadmap` (where this `v1` surface sits). One engine, one `Verdict`, many renderers.*
