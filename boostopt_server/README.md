# boostopt_server — the private hosted backend (premium tier)

> ⚠ **PRIVATE. Never published. Never shipped in the free `boostopt` client. Never imported by `boostopt`.**
> This is a **skeleton** — the *structure* is real (one-way dependency, server-side token gate, core reuse); the infra pieces are stubbed with `TODO(prod)`.

## The one rule (why this is a separate package, not a fork)

```
boostopt_server  ── imports ──▶  boostopt     (the shared, free-tier engine)
boostopt         ── imports ──▶  ∅          (never reaches back)
```

The dependency arrow points **one way**. `boostopt_server` **reuses** the free engine (gate,
orchestrator, adapters) — it never duplicates it, so there's no second copy to drift. And because
premium code lives in a *different package that isn't in the client's build*, the open client
**cannot** contain a paywall — there's no `if premium:` to sneak in. See `Docs/BOOSTOPT_Tiers.md` (P4).

## Run it

```bash
# from the repo root
python -m boostopt_server.app                    # → http://127.0.0.1:8724

# valid token → runs the core engine on "our" compute, returns the proof
curl -s localhost:8724/v1/optimize \
  -H "Authorization: Bearer vt_demo_trial" \
  -d '{"source":"#include <vector>\n#include <cstddef>\nstd::vector<int> f(std::size_t n){ std::vector<int> o; for(std::size_t i=0;i<n;++i) o.push_back((int)i); return o; }","filename":"f.cpp"}'

# no / bad token → 401, before any work is done (the paywall)
curl -s localhost:8724/v1/optimize -d '{"source":"..."}'
```

## Files

| File | Role | Real vs stub |
|---|---|---|
| `app.py` | HTTP API (`/v1/optimize`, `/healthz`) | real structure; stdlib server (prod: FastAPI/uvicorn) |
| `entitlement.py` | token → plan/features/model/quota — **the paywall** | **stub** in-memory dict → prod: auth DB + metered quota |
| `managed_model.py` | reuse `boostopt.engine.Engine` on our compute | **real** — this is the one-way dependency in action |

## How the free client will call it

`--model hosted` is a **thin, dumb HTTP client** inside the open CLI: it POSTs the function +
`boostopt-token` and prints the returned proof. It holds **zero** premium logic — all the value
(the managed model, the entitlement check, the compute) is here, server-side. That keeps the open
client un-crackable while still letting it *use* the paid service.

## Before this touches the internet (production TODOs)

- **Isolation is non-negotiable.** `/v1/optimize` **compiles and runs user-supplied code.** The
  engine sandboxes its child processes (item #13), but a multi-tenant host must *also* run each
  request in its own **container/VM** — no shared filesystem, no network egress. Do **not** expose
  this as-is.
- **Auth + quota:** replace the stub token dict with real API-key/OAuth + a database; decrement the
  metered quota in `entitlement.check` (this is where billing hooks in).
- **The managed model:** wire `model="frontier"` to BOOSTOPT's *own* inference endpoint (GPU box), so
  `boostopt-managed-coder` runs on our hardware — the whole point of the paid model.
- **Clean-room benchmarking** (`cleanroom` feature): route the verify step to dedicated, quiet
  hardware for deterministic timing (the honest-caveat upsell — `Docs/BOOSTOPT_Hosted.md` §6).
- **Packaging:** `boostopt_server/` must be **excluded** from the published free wheel
  (`pyproject.toml` packages `boostopt` only). Deploy it from its own private image.
- **Privacy:** hosted mode means the user's source leaves their box. Say so plainly (it's the
  free tier's whole differentiator that it *doesn't*).
