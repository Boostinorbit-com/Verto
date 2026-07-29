# VERTO Premium — explained simply and completely

*This document explains the paid version of VERTO from scratch. No prior knowledge is assumed — every term is defined in plain words, and every paid ability comes with a real "picture it" example and a before/after comparison. Read it top to bottom and you should have no unanswered questions. (For the exact command/flag split see [VERTO_Tiers](VERTO_Tiers.md); for the cloud concept from scratch see [VERTO_Hosted](VERTO_Hosted.md).)*

---

## The words you'll need (read this first — 60 seconds)

Just six terms. Everything else builds on these.

- **VERTO** — a tool that rewrites your C++ code to run faster, and **proves** the rewrite is still correct and actually faster before you keep it.
- **The check** — VERTO's built-in safety inspector. It re-tests every rewrite and only accepts one that is *still correct* **and** *measurably faster*. This is the heart of VERTO. **It is always free.**
- **Free version** — VERTO running entirely **on your own computer**: the tool, the check, the built-in rewrite rules, and a small AI you run locally. **Nothing you write ever leaves your machine.**
- **Premium (paid) version** — a few *extra* abilities that run on **VERTO's computers (servers)** instead of yours. You pay for these. It's optional.
- **Token** — a secret key that proves you've paid (like a password for the paid features). The free version needs none.
- **Server** — a computer that VERTO runs and owns, reached over the internet. "Hosted" and "on our servers" mean the same thing.

---

## 1. What Premium is, in one paragraph

VERTO is **free when it runs on your machine** — the whole tool, and the whole proof that your code is correct and faster. **Premium is an optional paid add-on** where a few heavy jobs run on **our** computers instead of yours: a **stronger AI**, **exact speed measurements**, and **team features**. You never pay for the proof itself. You only pay for our computers doing work your computer can't do well.

---

## 2. The one idea (an analogy)

> Think of VERTO like a **free photo app** on your phone. The app is free and does everything on your phone. **Premium is like sending a photo to a professional print lab** — you pay for the lab's expensive equipment and nice paper, not for the app. The photo is the same photo; you're paying for better equipment and convenience.

That's the whole model: **the app (and its proof) is free; you pay only for our lab.**

---

## 3. Why would anyone pay? (each paid thing, with a real example)

There are four paid abilities. Each one solves a real problem your own computer is bad at. For each, here's *the problem*, a *picture-it* example, and a *before/after*.

### 3.1 A stronger AI, with nothing to install ("managed model")

**The problem:** the AI that suggests rewrites, in the free version, runs on your computer's normal processor (its "CPU"). It's a **small** AI and **slow** — about **20 seconds per function** — and its ideas are hit-or-miss.

**Picture it:** you type `verto optimize hot_loop.cpp`. In the **free** version, the little AI thinks for ~20 seconds and suggests a decent-but-basic change. In the **paid** version, you type the *exact same command*, but the request goes to our **big, fast AI on a powerful graphics card (a "GPU")** — it answers in a second or two with a *smarter* rewrite (say, pre-sizing a list **and** removing an unnecessary copy). You installed nothing; you just have a token.

| | Free local AI | Paid managed AI |
|---|---|---|
| Speed | ~20 sec/function (your CPU) | ~1–2 sec (our GPU) |
| Quality of ideas | small model, hit-or-miss | large model, smarter rewrites |
| Setup | install an AI runner + download a model | nothing — just a token |
| Your code | never leaves your machine | is sent to our server |

*Plainly: "skip the slow little AI on your laptop; use our big one."*

### 3.2 Exact speed numbers ("clean-room benchmarking")

**The problem:** to claim *"this is faster,"* VERTO has to **time** the code with a stopwatch. But a stopwatch on a busy machine is unreliable — while VERTO is timing, your other apps (or a shared build server) grab the processor for a moment, and the number **jumps around**.

**Picture it:** VERTO tells you a change is **−30% faster**. You run it again — now it says **−16%**. Which is true? On your busy laptop, *both* readings are noisy. On our **clean-room** — a **dedicated machine doing nothing else** — you get the *same steady number every time*, say **−24%**, one you can actually put in a report. This also removes a real risk: a noisy stopwatch can occasionally make VERTO *think* a change is faster when it isn't.

| | Your laptop / shared CI | Our clean-room |
|---|---|---|
| The number | wobbles (−30%, then −16%) | steady and repeatable |
| Can you trust it? | comes with a "usually bigger on real hardware" caveat | a number you can quote |
| Risk | noise can fake a win | isolated, no noise |

*Plainly: "get a speed number you can actually trust."* (The free version is **honest** about the wobble for free — paid is what **removes** it.)

### 3.3 Team features — how several people work together

**The problem:** without team features, **each developer is an island.** VERTO runs on Alice's laptop and keeps its notes on *Alice's* laptop; it runs on Bob's laptop and keeps its notes on *Bob's* laptop. They can't see each other's work. Team features **connect the islands** by moving the shared parts onto our server — one shared brain instead of five separate ones.

**Picture it — a day at a 5-person C++ team ("Acme"):**

1. **The lead sets one rule for everyone.** Dana sets the team **policy** once: *"every accepted change must be sanitizer-clean, at least 5% faster, and must not use more memory."* Now **everyone's VERTO automatically obeys it** — no one can accept a weak or risky change by accident.
2. **Alice optimizes something, and the team remembers it.** Alice gets a proven **−40%** on the `match()` function and applies it. That result is saved to the **shared history on the server**, not just her laptop.
3. **Bob doesn't repeat her work.** A week later Bob edits near `match()`. His VERTO shows him *"already optimized by Alice — −40%, Mar 3,"* so he **doesn't waste a day re-discovering it.**
4. **Dana checks progress without the command line.** She opens the **dashboard** (a web page) and sees at a glance: *"12 verified speedups this month, 8 applied, 4 waiting for review,"* and which files.
5. **A new hire gets instant context.** Chen joins; IT gives him access via **company login** (he signs in with his normal Acme work account — no separate password). Day one, he sees all the team's history and rules.
6. **Security can prove what happened.** For a review, they export the **audit trail** — a permanent log of *"who applied which change, when, with the proof."*

**Every tiny team term, defined:**

| Term | Plain meaning | What it does for the team |
|---|---|---|
| **Shared history** | VERTO's notebook of what it tried/accepted, kept on the server instead of one laptop | Everyone sees everyone's wins → no duplicate work, lasting team memory |
| **Dashboard** | A web page (not the command line) showing the team's state | The lead sees progress at a glance, no commands |
| **Company policy** | One shared settings file the lead controls | Every dev's VERTO uses the same safety/quality bar |
| **Seats** | Paid slots, one per team member (5 people = 5 seats) | How the team plan is priced |
| **Company login (SSO)** | Sign in with your existing work account (Google/Okta), not a new password | IT controls access; easy on/off-boarding |
| **Audit trail** | A permanent log of who did what, when | Compliance, security reviews, accountability |

| | Solo / free | Team / paid |
|---|---|---|
| Where history lives | your laptop only | shared server, whole team sees it |
| Rules | each person sets their own | lead sets one policy for everyone |
| Seeing progress | run a command yourself | a web dashboard anyone can open |
| A new teammate | starts from zero | inherits all history + rules instantly |
| Proof of changes | in your local logs | a company-wide audit trail |

*Plainly: "for a team sharing a codebase — not a solo dev."* A solo developer genuinely doesn't need any of this.

### 3.4 Automatic checks on your pull requests, run by us ("hosted PR service")

**First, a definition:** a **pull request** (PR) is a *proposed* code change someone opens for review before it's merged into the shared codebase (on GitHub, GitLab, etc.).

**The problem:** VERTO already has a **free** tool that checks each PR automatically — but you have to **set it up to run inside your own system** (add a small config file, run it on your own machines).

**Picture it:** Alice opens a PR that touches `match()`. With the **hosted** service, you connected VERTO once, and now *every* PR is automatically checked **on our machines** — a comment appears on the PR: *"VERTO found a verified −40% speedup in `match()` — apply?"* — using the **strong AI** and **exact timing**, with **zero setup** on your side.

| | Free self-run | Paid hosted |
|---|---|---|
| Where it runs | your own CI / machines | our machines |
| Setup | add a config file to your repo | connect once, then automatic |
| AI + timing used | your local model + your runner | managed AI + clean-room |

*Plainly: "the free auto-checker, but hosted and hands-off."* (The self-run free version stays free.)

---

## 4. What it costs (the plans)

Four levels. **The actual prices are not decided yet** — this is only the *shape*. Everything on your own machine stays free at every level; a paid level only **adds** the hosted abilities above.

| Level | Who it's for | Includes | Price |
|---|---|---|---|
| **Free Trial (hosted)** | just trying the hosted side | a taste, with tight limits | free |
| **Pro** | one developer | the strong AI + exact speed numbers | *to be decided* |
| **Team** | a small team | Pro **+** shared history, dashboard, company rules, seats | *to be decided* |
| **Enterprise** | a whole company | Team **+** company login, audit trail, guarantees, on-premise option | *to be decided* |

**Which am I?** One person tinkering → **Free** (local) is plenty. One person wanting the strong AI / trustworthy numbers → **Pro**. Several people sharing a codebase → **Team**. A company needing login control and audit → **Enterprise**.

---

## 5. How Premium is built (and why it isn't a copy)

**We do not copy VERTO into a second project.** We keep **one** project and add a **separate private folder** (called `verto_server`) that **borrows** the free VERTO engine.

- **Why not copy it?** A copy would mean fixing every bug **twice**, and the two copies slowly **drifting apart** into two different products. Bad.
- **So instead:** the paid server **uses** the free engine directly. The free tool, on the other hand, **knows nothing** about the paid server.

Picture it as a one-way arrow — the paid side depends on the free side, never the reverse:

```
   your free tool  ──▶  our paid server  ──▶  the free VERTO engine
   (asks nicely)        (checks payment,       (does the actual
                         then borrows ▼)         optimizing + proof)
```

Nice side effect: because **none of the paid code lives inside the free tool**, if we ever open the free tool to the public, there's **no paid code hidden in it** to leak or hack around. The free tool is just a free tool.

---

## 6. How your computer talks to our server

When you use a paid feature, the free tool **sends your code to our server along with your token**. Our server checks the token, does the work, and **sends back the result**. That's it.

<details><summary><b>For engineers — the exact request</b></summary>

`POST /v1/optimize`, header `Authorization: Bearer <token>`:

```json
// you send
{ "source": "<your C++ code>", "filename": "f.cpp" }

// you get back
{ "plan": "pro",
  "results": [
    { "function": "f", "accepted": true, "p50_delta_pct": 62.5, "rung": 3,
      "diff": "--- a/f.cpp\n+++ ..." }
  ] }
```

Errors: `401` no/bad token · `403` your plan doesn't include this feature · `429` you hit your limit · `500` our fault. A runnable version is in `verto_server/`.
</details>

---

## 7. How paying is enforced (so it can't be cheated)

**The "have you paid?" check happens on *our* server, never inside the free tool.** This is deliberate.

**Picture it:** a clever user opens up the free tool's code (it's on *their* computer, after all) and tries to delete the "is this person paying?" line. In a badly-designed product, that would unlock the paid features for free. In VERTO it does **nothing** — because the check isn't in the tool at all. The paid features live on **our** server, and our server asks for a valid token *before doing any work.* No token → it politely refuses. There's simply no lock inside the free tool to pick.

---

## 8. Is it safe? (the one thing we must get right)

Our server **runs code that users send it** — it compiles and executes their C++. That is powerful and, if done carelessly, dangerous.

**Picture the threat:** a malicious user sends us C++ that tries to read *other* users' code, or delete our files, or call out to the internet. If we ran it plainly, it could.

> **The defense: every request runs in its own sealed box** (an isolated "container") that **cannot touch other users' work and cannot reach the internet**, with strict time and memory limits, and is **thrown away after each run.** So the worst a malicious request can do is waste its own little box, which we delete anyway.

This is the **single most important thing to build correctly**. The free tool already sandboxes the programs it runs on *your* machine, but hosting many strangers needs this extra sealed-box layer on top. **The current skeleton is safe for local/trusted use only — do not put it on the open internet as-is.**

---

## 9. What about my private code?

Be honest and upfront, because it's the opposite of the free version:

- **Free version:** your code **never leaves your computer** — that's its whole selling point.
- **Premium:** to use our servers, **your code comes to us**. There's no way around that — the work happens on our machines.
- **What we keep:** general *patterns* that help us improve the product — **not** your actual source code. (The exact keep/delete policy still needs writing down and showing to users.)

Users should choose this with eyes open. Many will happily send code to a trusted service; some won't — and for them, the free local version is always there.

---

## 10. When should we build this? (not yet — and here's why)

Premium is a whole **online service** (servers, logins, billing, powerful machines), not a small feature. The right order is:

1. **First, get people using the free tool.**
2. **Listen for the ask.** When users say *"I wish the AI were faster"* or *"I wish the speed numbers were exact,"* that's the signal.
3. **Then build the exact piece they're asking for** — probably the **stronger AI** first (most obvious value), or the **exact-timing** service.

Building an expensive online service **before anyone uses the free tool** is guessing with money. Free first, paid when there's real demand.

---

## 11. What we promise to NEVER charge for

So there's no confusion, and so we don't drift over time:

1. **The check** — the proof that a change is correct and faster. Free, always.
2. **Applying a change** — taking a proven improvement into your own code.
3. **The built-in rules and the local AI** — optimizing offline, on your machine.
4. **The free self-run PR checker** — VERTO in your own system.
5. **The tool itself** — the whole command-line program.

Paying only ever buys **our servers doing extra work** — never a better proof, and never unlocking something your own computer could already do.

---

## 12. Honest status (where this actually stands today)

- **Almost none of Premium is built.** It is a **plan plus a small working proof-of-concept** (a "skeleton" — the folder `verto_server/`) that shows the design works: it correctly refuses unpaid requests and, for a paid one, runs the real engine and returns the result.
- **The big pieces do not exist yet:** the powerful AI machines, the quiet timing machines, the team dashboard, logins, and billing.
- This document is the **plan to build them from** — and, on purpose, it comes **after** the free version has users.

---

## 13. Where to read more

| Document | What it's for |
|---|---|
| [VERTO_Tiers](VERTO_Tiers.md) | The exact free-vs-paid line, listed command by command, with the reason for each. |
| [VERTO_Hosted](VERTO_Hosted.md) | The "our-servers" idea explained from scratch, including when you *don't* need it. |
| `verto_server/README` | The small working skeleton, and the to-do list before it's production-ready. |
| [VERTO_CI_Action](VERTO_CI_Action.md) | The free pull-request checker (the hosted PR service is its paid sibling). |
