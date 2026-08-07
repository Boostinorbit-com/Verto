# BOOSTOPT Premium — Build Roadmap

*How to go from today's skeleton to a sellable paid service, one small step at a time — in plain words, in the right order, with the reason for each. This is the "how to build it" companion to [BOOSTOPT_Premium](BOOSTOPT_Premium.md) (the "what it is").*

---

## 0. The one rule before any step (the gate)

> **Do not build any of this until the *free* version is published and has real users.**

Why: Premium is a whole online service (servers, logins, billing, powerful machines). Building it before anyone uses the free tool is **spending money on a guess**. First ship free, get users, and listen for the ask (*"I wish the AI were faster," "I wish the speed numbers were exact"*). **That demand is the green light.** Everything below assumes the light is green.

---

## 1. Where we're heading (the picture)

We turn the **skeleton** (already built — the `boostopt_server/` folder) into a real service, adding the **smallest paid thing first** and growing outward:

```
   skeleton  ──▶  Pro (strong AI)  ──▶  + exact numbers  ──▶  + team  ──▶  + enterprise
   (today)        Phase 1–2             Phase 3               Phase 4      Phase 5
```

Each stage is **sellable on its own** — you make money at Pro, long before team/enterprise exist.

> **Progress — 2026-07-29 (dev mode).** The skeleton (`boostopt_server/`) and the free tool's **`--model hosted`** link are **built and working end-to-end locally**: `boostopt optimize f.cpp --model hosted --boostopt-token vt_demo_trial` → sends to the local server → runs the real engine → shows the verified result, **gated by the token** (a missing/bad token is refused). That's roadmap **steps 2.4 & 3.5 done**, plus the client↔server↔engine plumbing and the entitlement gate. **Also done since:**
> - **hosted `--apply`** — the server returns the fully-optimized file; the client writes it locally (dry-run still writes nothing).
> - the **`pro` token wired to a real AI** — `boostopt2.5-coder:7b` via Ollama (a genuine AI answer through the hosted path, no GPU).
> - **full hosted flag coverage** — all client-side output/apply flags now work (`--json` `--diff` `--apply` `--dry-run` `--backup` `--export` `--emit-patches` `--fail-on`).
> - **safe preference forwarding** — `--min-speedup` `--metamorphic` `--candidates` are sent to the server, which enforces they can only **tighten** the check, never weaken it (min-speedup only rises, metamorphic only turns on, candidates clamped ≤8); gate-**weakening** knobs and model choice stay **server-locked**.
> - **server DX** — restart **takes over the same port**, and it prints **IP/port + a request→response log** on the terminal.
> - **accounts & metering (Phase 2 core)** — a **persistent token store** (`store.py`) replaced the hard-coded dict: tokens survive restarts, an **admin CLI** issues/revokes them, and every run is **metered per month** with a hard cap (**429** over quota). Steps **4.3 & 4.4 done (dev)**.
> - **boundary is now test-locked** — the proprietary `boostopt_server` is excluded from the public wheel, and two tests (`test_boundary.py`) fail the build if it ever slips into the wheel or if the free client ever imports it (the paywall is architectural, so it's enforced, not just documented).
> - **Stripe webhook seam (money→token)** — `billing.py` + `POST /v1/webhooks/stripe` verify a **real Stripe signature** and mint a token on a paid checkout via `store.issue()`. Proven end-to-end in dev: *signed webhook → token → that token runs an optimize*. Only external bits (Stripe account/keys, email delivery) remain for 4.2.
>
> In dev the pieces we haven't built yet run on **stand-ins**: the `trial` token uses the **`rules`** engine, the `pro` token uses the **local** coder model, the "server" is `localhost`, and tokens are issued by the **admin CLI** instead of a payment webhook. **The plumbing is real; the heavy infra (GPU model, deployed hosting, sealed boxes, real payment) is still stand-ins.** Next: the payment provider (Stripe) + real sign-up/account UI (rest of Phase 2).

**Hosted flag coverage so far** (`--model hosted`):

| Category | Flags | Status |
|---|---|---|
| **Output / apply** (client) | `--json` `--quiet` `--diff` `--apply` `--dry-run` `--backup` `--export` `--emit-patches` `--fail-on` `--boostopt-token` `--hosted-url` | ✅ wired |
| **Safe preferences** (forwarded; the server can only *tighten*, never weaken) | `--min-speedup` `--metamorphic` `--candidates` | ✅ forwarded |
| **Gate / model** (locked to your plan, decided server-side) | `--min-rung` `--fuzz` `--seed` `--reps` `--no-adaptive` `--fp-tolerance` `--objectives` `--llm-model` `--llm-url` `--refine` `--no-cache` `--budget` `--fast` `--transforms` | 🔒 server-side |
| **Local / codebase** (n/a to hosted single-file) | `--test-command` `--bench-command` `--ctest-dir` `--profile` `--changed` `--jobs` `--force` | ⏭️ n/a |

---

## 2. Start here: the leanest test (my #1 recommendation)

Before building the full thing, answer the **only question that matters: will anyone actually pay for the hosted AI?** Build the cheapest version that can answer it:

- [ ] **2.1** Rent **one** cloud server with a graphics card (GPU).
- [x] **2.2** Put a **strong code AI** on it (bigger/smarter than the local one). **◑ dev** — the `pro` token uses the local `boostopt2.5-coder:7b` as a stand-in (real GPU model at release).
- [ ] **2.3** Point the skeleton at it, and **run each request in its own sealed box** (safety — see §9).
- [x] **2.4** Add **`--model hosted`** to the free tool (sends code + token to your server). **✅ done** — `boostopt/surfaces/hosted_client.py` (thin caller) + CLI `--boostopt-token`/`--hosted-url`.
- [ ] **2.5** **Skip billing code.** Use a simple **payment link**; when someone pays, **email them a token by hand** (or a tiny script).
- [ ] **2.6** Sell **"Pro"** to ~10 early users. Watch: **do they pay, and do they come back?**

**The decision:**
- ✅ **They pay** → build proper billing + the rest, in order below.
- ❌ **They don't** → stop. You just saved months building a cloud nobody wanted.

*This is days of work, not months. Do this before Phase 1's polish.*

---

## 3. Phase 1 — The stronger AI ("managed model")

The first real paid ability. (Steps 2.1–2.4 above are its rough version; here's the production version.)

- [ ] **3.1** Rent the GPU server(s) and put the strong code AI on it.
- [x] **3.2** Connect `boostopt_server`'s `managed_model.py` to that AI (replace the stub). **◑ dev done** — it runs the real engine with the plan's model (via the entitlement); the `pro` token points at the local coder AI. Same code → the GPU endpoint at release.
- [ ] **3.3** **Sealed box per request** — isolate every user's code run (safety, §9).
- [ ] **3.4** **Real accounts/login** — replace the fake token list with real auth (API keys or accounts).
- [x] **3.5** Finish **`--model hosted`** in the free tool (token + errors handled). **✅ done** — clean 401 / bad-token / server-down messages; `BOOSTOPT_TOKEN` env var; honest engine label (shows the *real* engine, e.g. "rules (dev stand-in)").
- [ ] **3.6** Put the server **online** — a web address, HTTPS (the padlock), always-on.
- [x] **3.7** **Test end to end** — a paying user runs `--model hosted` and gets a result. **✅ done** — the full loop is verified in dev (call → verify → show → `--apply`), incl. safe-preference forwarding; a GPU AI swaps in at release with no client change.

---

## 4. Phase 2 — Let people actually pay (billing & accounts)

- [ ] **4.1** A **sign-up page** — create an account.
- [ ] **4.2** **Payment** — hook up a provider (e.g. Stripe) with the Pro plan. **◑ partial** — the **webhook seam is built** (`boostopt_server/billing.py` + `POST /v1/webhooks/stripe`): it does the **real Stripe signature check** (HMAC-SHA256) and, on a paid checkout, calls `store.issue()` to mint the token — proven end-to-end in dev (signed webhook → token → the token runs an optimize). What's left is *external*: a real Stripe account, the price→plan IDs (`$STRIPE_PRICE_MAP` or `metadata.plan`), the signing secret (`$STRIPE_WEBHOOK_SECRET`), and emailing the token instead of logging it.
- [x] **4.3** **Issue a token when they pay** — paying → they get their secret key. **◑ dev done** — a **persistent token store** (`boostopt_server/store.py`) + an **admin CLI** (`python -m boostopt_server.admin issue --plan pro`) mints the secret; tokens survive restarts and can be revoked. At release the payment webhook (4.2) calls the same `store.issue()` — nothing else changes.
- [x] **4.4** **Count usage** — track how much each token uses; enforce limits; tie to billing. **✅ done (dev)** — **per-token, per-month metering**: the server reserves a run against the plan's monthly quota and returns **429** over the cap (0 = unlimited); usage is echoed in the response + the request log. *Tie-to-billing* is the only piece left (needs Stripe, 4.2).
- [ ] **4.5** A tiny **account page** — see your plan, usage, and token. **◑ partial** — no web page yet, but `admin usage <token>` / `admin list` already show plan + usage from the CLI.

> ✅ **After Phase 2 you have a real, sellable product: "Pro" = the strong AI, paid for automatically.**

---

## 5. Phase 3 — Exact speed numbers ("clean-room")

The second paid ability — the honest-caveat upsell.

- [ ] **5.1** Set up **dedicated, quiet machines** (nothing else runs on them).
- [ ] **5.2** Send the **"measure speed" step** to those machines for hosted users.
- [ ] **5.3** Return the **steady, trustworthy number**.
- [ ] **5.4** **Lock it** to the paying plans that include it.

---

## 6. Phase 4 — Team features (and the one place design matters)

For several people sharing a codebase.

- [ ] **6.1** Move **history** from each laptop to a **shared database** on the server.
- [ ] **6.2** **Build the web dashboard** — the page the team looks at. **← the one screen worth a Figma/mockup, and only now (see §9).**
- [ ] **6.3** **Company rules** — one shared settings the lead controls.
- [ ] **6.4** **Seats** — many users under one account.
- [ ] **6.5** **Company login (SSO)** + an **audit trail**.

---

## 7. Phase 5 — Enterprise (big companies)

- [ ] **7.1** Corporate login (SSO with Okta/Entra, etc.).
- [ ] **7.2** Audit / compliance features.
- [ ] **7.3** **On-premise option** — run it inside the company's own cloud.
- [ ] **7.4** Contracts, SLAs (guarantees), and support.

---

## 8. Runs through everything (don't skip)

These aren't a phase — they apply to **every** step from Phase 1 on:

- [ ] **Security** — the sealed box per request (§9); never expose the skeleton as-is.
- [ ] **Monitoring** — know when the server is down or slow.
- [ ] **Reliability** — backups, restarts, sensible limits.

---

## 9. Where a design / Figma is actually needed

Almost nowhere — because almost nothing in Premium has a screen:

| Piece | Needs a design? |
|---|---|
| CLI, `--model hosted`, the API | ❌ text / code |
| Managed AI, clean-room | ❌ invisible backend |
| Hosted PR comment | ❌ just a text comment |
| Sign-up / account / billing pages | ~ standard SaaS screens (light) |
| **The team dashboard (Phase 4)** | ✅ **yes — the one real UI, and only at Phase 4** |

So: **no Figma needed until Phase 4**, and even then a simple mockup is enough to start.

---

## 10. Honest status & how to read this

- **Nothing here is built** beyond the skeleton (`boostopt_server/`), which proves the design works.
- **Each phase is sellable on its own** — you don't build all five before earning; you sell **Pro** after Phase 2 and grow from revenue.
- **The order is deliberate:** cheapest, highest-value thing first (the strong AI), then the next, gated by real demand at each step.
- **Timelines aren't given on purpose** — they depend on the team and shouldn't be guessed here.

---

## 11. Related docs

| Document | What it's for |
|---|---|
| [BOOSTOPT_Premium](BOOSTOPT_Premium.md) | **What** Premium is — every paid ability explained with examples. |
| [BOOSTOPT_Tiers](BOOSTOPT_Tiers.md) | The exact free-vs-paid line, command by command. |
| [BOOSTOPT_Hosted](BOOSTOPT_Hosted.md) | The "our-servers" idea from scratch. |
| `boostopt_server/README` | The working skeleton + its production to-do list. |
| [BOOSTOPT_Roadmap](BOOSTOPT_Roadmap.md) | The overall product roadmap (Premium is Phase 5, items #19–21). |
