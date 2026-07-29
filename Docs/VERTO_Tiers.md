# VERTO — Free vs Premium, decided at the command/flag level (and *why*)

*Companion to [VERTO_Hosted](VERTO_Hosted.md) (the cloud tier) and [VERTO_Surfaces](VERTO_Surfaces.md) (the full CLI). This doc makes the tiering decision concrete — every command and flag, sorted, with the reason.*

---

## 0. The one rule (TL;DR)

> **Free = everything that runs entirely on your machine.**
> **Premium = capabilities that need VERTO's servers.**
> **The gate — the proof a change is correct-AND-faster — is free forever.**

That's the whole policy. Almost the *entire* current CLI is free, because almost all of it runs locally. Premium is **additive hosted value**, not a lock on what already works.

---

## 1. Four principles (the *why* behind the rule)

**P1 — Never paywall the gate.**
The verification (differential test + sanitizers + Pareto + metamorphic) *is* the product's trust. A paywalled proof is worthless — a user who can't verify for free has no reason to believe us, and every competitor gives basic checks away. The gate must also be **inspectable** to be trusted. So: correctness and performance verification are free, always, no exceptions.

**P2 — Local-first is free.**
VERTO's moat is *local, private, inspectable*. Anything that runs on the user's own hardware costs us **nothing at the margin**, builds adoption and trust, and is exactly the thing that differentiates us. Giving it away is the strategy, not a concession. This covers the CLI, the rule library, the **local LLM**, and the **self-run CI Action** (it runs in *your* CI, on *your* compute).

**P3 — Premium = hosted value with real marginal cost.**
Charge only where we spend real money and add real value: **our compute** (a managed model, clean-room benchmarking) or **our infrastructure** (team dashboards, shared history, org policy). These have genuine cost per use and genuine convenience/quality upside — fair to charge, and honest.

**P4 — Gating is architectural, never a feature-flag in the client.**
There is **no `if premium:` in the open client.** The free client is fully functional on its own. A premium capability is a *service call* gated by a **`verto-token` + server-side entitlement** — a flag that needs the server simply *fails without a token*, it is not "present but disabled." This is what stops the "just patch the OSS client" crack, and keeps the free tier honest.

---

## 2. The test you apply to any new flag

> **"Does this run entirely on the user's machine, or does it call VERTO's servers?"**
> Local → **free**. Server → **premium** (needs a `verto-token`).

Every classification below is just this question, applied.

---

## 3. FREE — the whole local product

Every command, and every flag that acts locally. This is ~95% of the surface.

### Commands (all free)
| Command | Why free |
|---|---|
| `verto analyze` | Inspect opportunities locally — no writes, no server. |
| `verto optimize` | The core loop, runs on your machine. |
| `verto report` | Reads your local ledger. |
| `verto init` | Sets up the local `.verto/` workspace. |
| `verto serve` | A warm **local** daemon — your process, your socket. |

### The gate & verification (free — **P1**, never paywalled)
`--min-rung` · `--min-speedup` · `--objectives` · `--fuzz` · `--seed` · `--fp-tolerance` · `--metamorphic` · `--reps` · `--reps-min` · `--no-adaptive` · `--fast`
→ *These decide **whether a change is accepted**. Paywalling any of them would paywall the proof. Off the table. (`--fast` is the local sound-vs-speed toggle — it skips the sanitizer rung on request and loudly labels the result unsound; still local, still free.)*

### Proposers — rules & **local** LLM (free — **P2**)
`--model rules` · `--model local` · `--offline` · `--llm-model` · `--llm-url` · `--candidates` · `--refine` · `--no-cache`
→ *Rules run locally; the local LLM runs on your box (Ollama) — your source never leaves. The best-so-far cache is local state.*

### Reach oracles — **your** tests & profile (free)
`--test-command` · `--test-dir` · `--test-timeout` · `--bench-command` · `--bench-dir` · `--bench-runs` · `--build-command` · `--ctest-dir` · `--profile`
→ *These point VERTO at **your** test suite / profile on **your** machine. Nothing hosted.*

### Apply, output, patches (free)
`--apply` · `--dry-run` · `--diff` · `--emit-patches` · `--backup` · `--force` · `--apply-from` · `--json` · `--export` · `--quiet` · `--stop`
→ *Writing a verified change to your own source, or emitting a patch series, is local. **Apply is never paywalled** — a verified win you can't take is pointless.*

### Scale, sandbox, budget-meter (free)
`--changed` · `--jobs` · `--no-sandbox` · `--sandbox-mem` · `--budget` · `--budget-per-hotspot`
→ *Git-scoping, local parallelism, the local sandbox, and the **local** spend-meter (it just counts — it doesn't call us).*

### CI (self-run) & setup (free)
`--fail-on` · `--compile-commands` · `--verify-setup` · `--list-transforms` · `--transforms` · `--pull` · `--config` · `--config-file` · `--no-daemon` · `--no-color` · `--all` · `--global` · `--version`
→ *The **self-run GitHub Action** is free — it runs in your CI on your runners. Setup/inspection commands are local.*

---

## 4. PREMIUM — hosted add-ons (need VERTO's servers)

These are mostly **new** surface, not existing flags being locked. Each has real marginal cost *and* real added value.

| Capability | Surface (planned) | Why premium |
|---|---|---|
| **Managed model** — zero-setup, curated frontier model, no API key, no local GPU | `--model hosted` (+ `--verto-token`) | Runs on **our** compute; we pay for inference. Value = a strong model with *nothing to install or configure* (vs. the free local 7B on your CPU). |
| **Clean-room benchmarking** — deterministic, noise-free timing on dedicated hardware | `--bench remote` / hosted verdict | The durable fix for noisy cloud/CI timing (see [VERTO_Hosted](VERTO_Hosted.md) §6). Runs on **our** isolated boxes; real infra cost, materially better verdicts. |
| **Team / org layer** — shared optimization history, cross-repo baselines, org-wide policy, dashboards | new `verto team …` surface + web dashboard | Stateful, multi-user, hosted. Collaboration + governance value a single dev doesn't need. |
| **Hosted PR service** — the Action run *for* you on managed compute, with the dashboard | hosted mode of the Action | We supply the compute + the managed model + the history. (The **self-run** Action stays free.) |
| **Managed-model spend** — actual billing for hosted inference | metered via `--verto-token` | Pass-through + margin on real inference cost. The **local** `--budget` meter stays free. |

**The unlock is one thing:** a **`verto-token`** (already the Action's `verto-token` input). No token → the hosted paths fail cleanly; everything local still works. That is the entire gating mechanism (**P4**).

---

## 5. The gray areas (called out honestly)

| Flag | Ruling | Why |
|---|---|---|
| `--model frontier` | **Free** (BYO key) | You bring your *own* OpenAI-compatible endpoint + key (an env var). It never touches our servers, so it's free. It becomes premium **only** when pointed at *VERTO's managed* endpoint (that's `--model hosted`). |
| `--budget` / `--budget-per-hotspot` | **Free** (as a meter) | Counting/limiting spend is local. It only *bills* when the spend is on our **managed** model — and that billing is the premium part, not the flag. |
| The GitHub Action | **Free to self-run** | Runs in *your* CI on *your* runners. Premium only in **hosted** mode (our compute + dashboard). |
| `--profile` | **Free** | Consumes *your* `perf.data`. A *hosted profiler* would be a separate premium capability, not this flag. |

The pattern: **the flag is usually free; the hosted *backend* it can point at is what's paid.** That keeps the client honest and un-cracked (**P4**).

---

## 6. What we commit to NEVER paywall

A short list, so it's unambiguous — and so we don't drift:

1. **The gate** — accept ⟺ correct ∧ faster. The proof is free.
2. **`--apply`** — taking a verified win into your own code.
3. **Rules + the local LLM** — proposing, fully offline.
4. **The self-run CI Action** — VERTO in *your* pipeline.
5. **The CLI itself** — analyze / optimize / report / init / serve.

If a future flag would paywall any of these, it's the wrong flag.

---

## 7. One-line summary for the pitch

> **VERTO is free where it runs on your machine — the whole optimizer, the whole proof. You pay only for our servers doing what your laptop can't: a managed model, clean-room timing, and the team layer.**
