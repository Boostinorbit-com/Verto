# VERTO Hosted — the cloud version, explained from scratch

**This document explains roadmap item #19: "hosted / cloud" — a version where VERTO runs on *our* machines instead of yours, so you need no local setup.** It assumes no prior knowledge: every term is defined the first time it appears. It also says, honestly, when you *don't* need this.

---

## 1. What "hosted" means, and the one confusion to clear first

VERTO can run in three places. Don't mix them up:

| Where VERTO runs | What it is | Your code goes to |
|---|---|---|
| **Your laptop** (the CLI) | you run `verto` yourself | stays on your machine |
| **Your CI** (#18, the Action) | runs on *your* CI runners, in your pipeline | stays in your CI environment |
| **Our cloud** (#19, this doc) | runs on **VERTO's** machines | **sent to VERTO's servers** |

So "hosted" means: **you don't install or run anything; you point VERTO at your code and it does the compiling, sanitizing, and benchmarking on its own hardware.** The trade for that convenience — your code leaves your environment — is the whole discussion below (§5).

---

## 2. The idea in one picture

```
   You connect a repository (once)
            │
            ▼
   VERTO's cloud picks up each change and, on its OWN machines:
     · compiles it            (in an isolated worker)
     · differential-tests it  (identical output? → CORRECT)
     · runs sanitizers        (hidden bugs?)
     · benchmarks it          (on QUIET, dedicated hardware → trustworthy numbers)
            │
            ▼
   Results come back to you — a PR/MR comment, or a web dashboard.
   You installed nothing. No clang, no runner, no config on your side.
```

The point of difference from the CI Action (#18) is the **"on its OWN machines"** line — and specifically that those machines are *quiet and dedicated*, which matters more than it sounds (§6).

---

## 3. The words you need (each defined once)

- **Hosted / Cloud / SaaS** — "Software as a Service." Instead of you running the software, a provider runs it for you and you use it over the internet. Gmail is SaaS; this is VERTO as SaaS.
- **Build farm** — a **pool of machines that do the compiling and benchmarking**. When many people's jobs arrive, the farm spreads them across many workers.
- **Worker** — **one machine (or container) in the farm** that handles one job: compile → test → benchmark → report.
- **Queue** — a **waiting line for jobs.** Changes come in faster than any single machine can process, so they wait in a queue and workers pull from it.
- **Control plane** — the **"brain" of the service**: it handles logins, decides which job runs where, tracks results, and does billing. (The workers are the "muscle"; the control plane is the "brain.")
- **Multi-tenant** — **one shared service used by many customers at once** (like an apartment building). Cheapest to run; but everyone's data lives in the same system.
- **Single-tenant** — **a separate, isolated instance per customer** (like a private house). More expensive; stronger isolation.
- **On-prem / BYOC** — "on-premises" / "Bring Your Own Cloud" — **VERTO's software runs inside the customer's own datacenter or cloud account**, so their code never leaves *their* environment. The privacy-friendly option.
- **GPU serving** — running the LLM on **graphics processors (GPUs)**, which are much faster at AI models than normal CPUs. A hosted service centralizes this so users don't need their own GPU.
- **Isolation (VM / container / Firecracker)** — keeping each job **walled off** so one customer's code can't see or affect another's. A **container** is a lightweight wall; a **VM** (virtual machine) is a stronger wall; **Firecracker** is a tiny fast VM built for exactly this (running many untrusted jobs safely).
- **Baseline** — a **saved "before" measurement** of how fast something was, so a later run can tell whether a change made it faster or slower.
- **Flywheel** — a **self-reinforcing loop**: the more code VERTO optimizes, the more it learns which optimizations tend to work, so it gets better and faster for the next user. (More below — §7.)

---

## 4. What running "hosted" actually does, step by step

1. **You connect a repo once** (grant read access, pick settings). No install.
2. On each change, VERTO **queues a job**.
3. A **worker** in the build farm picks it up, in an **isolated** environment.
4. The worker **compiles, differential-tests, runs sanitizers, and benchmarks** the candidate optimizations — the exact same gate as the CLI, just on VERTO's hardware.
5. Results are **returned to you** — as a PR/MR comment (same layout as #18) and/or on a **web dashboard**.
6. What VERTO *learned* (which optimization patterns worked) updates the shared **flywheel** — never your private code, just the patterns (§7).

The engine doing the work is identical to the CLI. Hosting changes *where* it runs and *who provides the machines* — not *what* it does.

---

## 5. The big trade-off: your code leaves your box

This is the crux, and it must be said plainly. VERTO's defining promise everywhere else is *"runs on your machine; your source never leaves."* **A multi-tenant hosted service breaks that** — your code is sent to VERTO's servers to be compiled and benchmarked.

Three **deployment models** resolve this differently — a privacy ladder:

| Model | Where your code lives | Convenience | Privacy |
|---|---|---|---|
| **Multi-tenant SaaS** | on VERTO's shared servers | highest | lowest |
| **Single-tenant** | on a VERTO-run instance dedicated to you | high | medium |
| **On-prem / BYOC** | **in your own cloud/datacenter** | medium | **highest** |

**Recommendation: lead with on-prem / single-tenant.** It keeps VERTO's privacy advantage, defers the biggest liability (being custodian of everyone's private source), and it's the form enterprises — the buyers — prefer anyway. A public multi-tenant SaaS is the heaviest, most sensitive version; build it only if the market clearly pulls for it.

---

## 6. The real reason to host: clean-room benchmarking

Here is the value that *justifies* hosting — and it isn't "convenience."

Building VERTO's own CI taught us something the hard way: **shared CI runners are noisy computers, and noisy computers give unreliable speed measurements.** A change that's genuinely 30% faster can measure as 1% faster on a busy runner, because other people's jobs are stealing the CPU. VERTO, being honest, then reports a smaller win — or none.

A **hosted build farm fixes this at the source**: VERTO controls the hardware, so it can run benchmarks on **quiet, dedicated, pinned machines** — a "clean room." That yields **numbers you can actually trust**, which a shared GitHub/GitLab runner *cannot* give.

So the honest pitch for hosting is: *"Run it in your CI and get honest-but-caveated numbers; route the benchmark to our clean room and get numbers you can trust."* That's a real, differentiated value — not just saving you a `clang` install.

---

## 7. The "shared cache," honestly — patterns, not your code

It's tempting to promise a "shared cache of verified results." Be precise, because a naive version over-promises:

- **What you CANNOT share:** one repo's actual *verdict*. "This change is correct-and-faster" depends on the exact code *and* the exact compiler/CPU — it doesn't transfer to a different codebase.
- **What you CAN share (the flywheel):** the **patterns and priors** — e.g. *"pre-sizing a vector that's grown in a loop wins ~95% of the time"* — and **model responses for structurally-similar code**. These make the next optimization *faster to find and cheaper to propose*, across everyone.

So the shared cache is really a **growing library of proven optimization *patterns***, not a store of anyone's private results. That's still a genuine network effect — the more VERTO sees, the smarter its *proposing* gets — and it's honest.

---

## 8. Does hosting even beat just using the CI Action (#18)?

Worth asking bluntly, because **#18 already gives you "no local setup"** — it runs in your CI, and your code stays in your environment. So what does the heavier #19 add? Exactly three things:

1. **Clean-room benchmarking** — reliable numbers (§6). *The strongest reason.*
2. **The flywheel** — cross-customer pattern learning (§7).
3. **Managed compute** — VERTO's farm does the heavy compiling/benchmarking, instead of burning *your* CI minutes.

If those three aren't compelling for your buyers, **#18 + on-prem may be enough for a long time.** Don't build a build farm before demand proves you need one.

---

## 9. The architecture, in plain words

A hosted service is a real backend with several parts:

- **Control plane** — logins, projects, job scheduling, billing (the brain).
- **Queue + worker farm** — jobs wait in a queue; workers pull and run them, each **strongly isolated** (at multi-tenant scale, per-job micro-VMs like Firecracker — a lightweight container wall isn't enough when you're running strangers' code).
- **GPU model serving** — the LLM, centralized on GPUs.
- **Storage** — results, baselines, the pattern library.
- **Tightly coupled to security & legal (#21)** — the moment you hold customers' private source, data policy, encryption, and a security review stop being optional.

This is the **most capital-, infrastructure-, and liability-heavy item in the whole roadmap.**

---

## 10. The one screen you'd design (the dashboard) — and where Figma fits

Almost all of #19 is backend, with no UI. The exception is a **web dashboard**: connect-a-repo onboarding, a results view (optimizations + diffs), trends over time, and account/billing pages.

**This dashboard is the single surface in the entire roadmap that genuinely warrants product/UX design (Figma).** Everything else is a terminal or a PR comment. But two caveats: it's the **last mile of the last item** (don't design it before the backend exists or demand is proven), and even then **start functional** — an off-the-shelf dashboard component kit — and invest in custom design **only once paying customers justify the polish.**

---

## 11. Free vs paid — where hosting sits

Hosting is squarely a **paid / enterprise tier**, because it costs real money to run (machines, GPUs, storage):

- **Free:** the open-source CLI, and a basic self-run Action.
- **Paid — hosted:** managed compute + clean-room benchmarking + the dashboard + the flywheel + support. Offered **on-prem/single-tenant** for privacy-sensitive teams, and (if the market wants it) multi-tenant SaaS for the convenience-first.

The verification gate is identical at every tier — paying changes *where it runs and how reliable the numbers are*, never whether a bad change could slip through.

---

## 12. Status and honest cautions

- **Not built** — #19 is a Phase-5 (commercial) item, and the **heaviest and last** one.
- **Do it after product-market fit** — after the CLI, the #18 Action, and on-prem/self-hosted have shown real demand. A build farm before demand is burning money on infrastructure nobody's asked for yet.
- **Privacy is the pivot** — how you handle "customer code on our servers" (via on-prem/single-tenant) determines whether hosting strengthens or *undermines* VERTO's core promise.

---

## 13. Quick answers to the obvious questions

- **Is my code safe if it's hosted?** In multi-tenant SaaS it lives on VERTO's servers (encrypted, isolated, but present). Prefer **on-prem/BYOC**, where your code never leaves your own cloud. That's the recommended default for anyone sensitive.
- **Do I still need `clang` installed?** No — the whole point of hosting is that VERTO's machines have the toolchain. You install nothing.
- **Is it cheaper than running it in my own CI?** Sometimes — VERTO's farm replaces your CI minutes with dedicated hardware, and the benchmarks are more reliable. Whether that's cheaper depends on your usage.
- **Why not just use the CI Action (#18)?** If "no local setup + code stays with me" is all you want, **#18 already does that.** Hosting is for the extra three things in §8 — chiefly reliable benchmarking.
- **Does hosting make the suggestions less safe?** No. Same gate everywhere — every suggestion is still proven behavior-identical and faster before you see it.

---

*Companion docs: `VERTO_CI_Action` (the #18 Action, closely related), `VERTO_Surfaces` (all surfaces), `VERTO_Roadmap` (where #19 sits, and why it's last). One fact, one home.*
