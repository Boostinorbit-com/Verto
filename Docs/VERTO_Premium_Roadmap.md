# VERTO Premium — Build Roadmap

*How to go from today's skeleton to a sellable paid service, one small step at a time — in plain words, in the right order, with the reason for each. This is the "how to build it" companion to [VERTO_Premium](VERTO_Premium.md) (the "what it is").*

---

## 0. The one rule before any step (the gate)

> **Do not build any of this until the *free* version is published and has real users.**

Why: Premium is a whole online service (servers, logins, billing, powerful machines). Building it before anyone uses the free tool is **spending money on a guess**. First ship free, get users, and listen for the ask (*"I wish the AI were faster," "I wish the speed numbers were exact"*). **That demand is the green light.** Everything below assumes the light is green.

---

## 1. Where we're heading (the picture)

We turn the **skeleton** (already built — the `verto_server/` folder) into a real service, adding the **smallest paid thing first** and growing outward:

```
   skeleton  ──▶  Pro (strong AI)  ──▶  + exact numbers  ──▶  + team  ──▶  + enterprise
   (today)        Phase 1–2             Phase 3               Phase 4      Phase 5
```

Each stage is **sellable on its own** — you make money at Pro, long before team/enterprise exist.

> **Progress — 2026-07-29 (dev mode).** The skeleton (`verto_server/`) and the free tool's **`--model hosted`** link are **built and working end-to-end locally**: `verto optimize f.cpp --model hosted --verto-token vt_demo_trial` → sends to the local server → runs the real engine → shows the verified result, **gated by the token** (a missing/bad token is refused). That's roadmap **steps 2.4 & 3.5 done**, plus the client↔server↔engine plumbing and the entitlement gate. **Also done since:**
> - **hosted `--apply`** — the server returns the fully-optimized file; the client writes it locally (dry-run still writes nothing).
> - the **`pro` token wired to a real AI** — `verto2.5-coder:7b` via Ollama (a genuine AI answer through the hosted path, no GPU).
> - **full hosted flag coverage** — all client-side output/apply flags now work (`--json` `--diff` `--apply` `--dry-run` `--backup` `--export` `--emit-patches` `--fail-on`).
> - **safe preference forwarding** — `--min-speedup` `--metamorphic` `--candidates` are sent to the server, which enforces they can only **tighten** the check, never weaken it (min-speedup only rises, metamorphic only turns on, candidates clamped ≤8); gate-**weakening** knobs and model choice stay **server-locked**.
> - **server DX** — restart **takes over the same port**, and it prints **IP/port + a request→response log** on the terminal.
>
> In dev the pieces we haven't built yet run on **stand-ins**: the `trial` token uses the **`rules`** engine, the `pro` token uses the **local** coder model, and the "server" is `localhost`. **The plumbing is real; the heavy infra (GPU model, deployed hosting, sealed boxes, billing) is still stand-ins.** Next: billing/accounts (Phase 2).

---

## 2. Start here: the leanest test (my #1 recommendation)

Before building the full thing, answer the **only question that matters: will anyone actually pay for the hosted AI?** Build the cheapest version that can answer it:

- [ ] **2.1** Rent **one** cloud server with a graphics card (GPU).
- [ ] **2.2** Put a **strong code AI** on it (bigger/smarter than the local one).
- [ ] **2.3** Point the skeleton at it, and **run each request in its own sealed box** (safety — see §9).
- [x] **2.4** Add **`--model hosted`** to the free tool (sends code + token to your server). **✅ done** — `verto/surfaces/hosted_client.py` (thin caller) + CLI `--verto-token`/`--hosted-url`.
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
- [ ] **3.2** Connect `verto_server`'s `managed_model.py` to that AI (replace the stub).
- [ ] **3.3** **Sealed box per request** — isolate every user's code run (safety, §9).
- [ ] **3.4** **Real accounts/login** — replace the fake token list with real auth (API keys or accounts).
- [x] **3.5** Finish **`--model hosted`** in the free tool (token + errors handled). **✅ done** — clean 401 / bad-token / server-down messages; `VERTO_TOKEN` env var; honest engine label (shows the *real* engine, e.g. "rules (dev stand-in)").
- [ ] **3.6** Put the server **online** — a web address, HTTPS (the padlock), always-on.
- [ ] **3.7** **Test end to end** — a paying user runs `--model hosted` and gets a result from your GPU AI.

---

## 4. Phase 2 — Let people actually pay (billing & accounts)

- [ ] **4.1** A **sign-up page** — create an account.
- [ ] **4.2** **Payment** — hook up a provider (e.g. Stripe) with the Pro plan.
- [ ] **4.3** **Issue a token when they pay** — paying → they get their secret key.
- [ ] **4.4** **Count usage** — track how much each token uses; enforce limits; tie to billing.
- [ ] **4.5** A tiny **account page** — see your plan, usage, and token.

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

- **Nothing here is built** beyond the skeleton (`verto_server/`), which proves the design works.
- **Each phase is sellable on its own** — you don't build all five before earning; you sell **Pro** after Phase 2 and grow from revenue.
- **The order is deliberate:** cheapest, highest-value thing first (the strong AI), then the next, gated by real demand at each step.
- **Timelines aren't given on purpose** — they depend on the team and shouldn't be guessed here.

---

## 11. Related docs

| Document | What it's for |
|---|---|
| [VERTO_Premium](VERTO_Premium.md) | **What** Premium is — every paid ability explained with examples. |
| [VERTO_Tiers](VERTO_Tiers.md) | The exact free-vs-paid line, command by command. |
| [VERTO_Hosted](VERTO_Hosted.md) | The "our-servers" idea from scratch. |
| `verto_server/README` | The working skeleton + its production to-do list. |
| [VERTO_Roadmap](VERTO_Roadmap.md) | The overall product roadmap (Premium is Phase 5, items #19–21). |
