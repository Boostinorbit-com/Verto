# BOOSTOPT → PyPI: upload roadmap

**Status as of 2026-08-09: not ready to upload.** Three things block it, only one of which is
engineering. This document is the whole picture — where we are, what's decided, what's left, in
what order, and who does each part.

Companion docs: `BOOSTOPT_Publishing.md` (the exact commands), `BOOSTOPT_Packaging.md` (how the
closed-source wheel is built), `RELEASING.md` (policy and tagging).

---

## 1. The short answer

| | |
|---|---|
| **Can we upload today?** | No |
| **What's blocking?** | Legal review · website URLs · compiled wheels not yet built on CI |
| **What can we do today?** | A TestPyPI rehearsal — safe, claims nothing |
| **How far off?** | Days, not weeks. None of the remaining work is hard. |

The single most important fact: **uploading the wheel that `python -m build` produces would
publish your source code.** It contains ~80 readable `.py` files including `engine/gate.py`. The
closed-source artifact exists and is proven, but has not been produced on CI yet.

---

## 2. Decisions already made — no further discussion needed

| Decision | Settled as | Where it lives |
|---|---|---|
| Licence model | Proprietary commercial EULA | `LICENSE` |
| Governing law | India | EULA §11.1 |
| Free tier scope | Unlimited — no seat, machine, or CI-runner cap | EULA §2 |
| Premium gating | Subscription key, hosted service only | EULA §3 |
| Package name | `boostopt` — verified free on PyPI 2026-08-09 | `pyproject.toml` |
| Domain | `boostopt.com` only — no subdomains | all metadata |
| Source visibility | **Closed** — never published anywhere | drives §4 below |
| Distribution | pip now, apt later | `install.sh`, roadmap §6 |

---

## 3. What is already built and verified

Nothing in this list is outstanding work.

- **Package metadata** — `LicenseRef-BoostOpt-EULA`, `LICENSE` + `NOTICE` ship in the wheel, all
  project URLs on `boostopt.com`, `twine check` passes.
- **`boostopt demo`** — the quickstart works from a bare `pip install`, because its sample is a
  module constant rather than package data.
- **Compiled build** — Nuitka produces a single `.so`; a wheel containing it installs and runs
  with **zero `.py` files** (`boostopt demo` → ACCEPT, −67%).
- **`tools/build_native_wheel.py`** — builds and verifies that wheel; exits non-zero if any `.py`
  survives or `boostopt_server` leaks.
- **`.github/workflows/release-wheels.yml`** — 9-wheel matrix, manual trigger, Trusted Publishing.
- **`boostopt-uninstall`** — full teardown, removing only what a provenance receipt claims.
- **Test suite** — 236 passed, 3 skipped. Open-core boundary enforced by tests.

---

## 4. The three blockers

### 4.1 Legal review — **owner: you**

The EULA is complete but **unreviewed**. Two clauses need a solicitor's eye before publication:

- **§8 (no warranty)** — disclaims warranty on the verification itself. BOOSTOPT's entire claim is
  "proven correct and faster", so a customer's lawyer reads this clause against your marketing
  first. It needs to survive that reading.
- **§9 (liability cap)** — capped at the greater of twelve months' fees or USD 100. Indian
  consumer-protection law may limit what is enforceable.

Publishing binds you to whatever the file says. This is the only blocker with no technical
workaround.

### 4.2 Website URLs must resolve — **owner: you**

The wheel metadata and the licence text both reference pages that currently 404:

| Path | Referenced by | Priority |
|---|---|---|
| `/privacy` | **EULA §7** | **highest** — cited in a legal document |
| `/docs` | PyPI sidebar, CLI `--help`, README | high |
| `/support`, `/changelog` | PyPI sidebar | medium |
| `/license` | README | medium |
| `/docs/flags`, `/docs/overview`, `/docs/architecture`, `/docs/surfaces` | README table | low |
| `/install.sh` | README quickstart — must serve the real script | high |

A stub page per path is enough to start. Publishing with a dead `/privacy` is the one to avoid.

### 4.3 Compiled wheels not yet built on CI — **owner: me, runnable now**

The pipeline works locally, but its output is tagged `linux_x86_64`, **which PyPI rejects**.
Converting that to `manylinux_2_28_x86_64` needs `auditwheel repair`, which requires `patchelf`
and has never actually run — it is wired into the workflow but untested.

Run `release-wheels` manually on GitHub to exercise it. If it builds clean, this blocker closes.

---

## 5. The path, in order

```
Phase 1  TestPyPI rehearsal              ← can start TODAY, safe, claims nothing
Phase 2  Legal review          (you)     ─┐
Phase 3  Website URLs live     (you)     ─┼─ these three run in parallel
Phase 4  Compiled wheels on CI (me)      ─┘
Phase 5  Publish to PyPI                 ← one-way door
Phase 6  Tag, announce, then apt
```

### Phase 1 — TestPyPI rehearsal (today)

Validates credentials, metadata rendering, and a clean-venv install end to end. TestPyPI is
throwaway and reserves nothing on real PyPI, so it carries no risk. Commands: `BOOSTOPT_Publishing.md` §3–4.

Prerequisite: register on **both** pypi.org and test.pypi.org (separate accounts), enable 2FA on
both, save the recovery codes.

### Phase 2 — Legal review

See §4.1. Send counsel `LICENSE` and `NOTICE` together — the third-party attributions matter.

### Phase 3 — Website

See §4.2. Stub pages are acceptable; `/privacy` and `/install.sh` need real content.

### Phase 4 — Compiled wheels

Trigger `release-wheels` with `publish: false`. Confirm every job produces a wheel with `.py: 0`
and a `manylinux` tag. Decide at this point whether macOS and Windows are launch platforms —
`README.md` says v0 is **Linux-only**, so 3 wheels may serve where the matrix currently builds 9.

### Phase 5 — Publish

Upload claims the name **permanently**. PyPI allows yanking a version but never releases or
reuses a project name. Do not run this until Phases 2–4 are complete.

### Phase 6 — After

Tag `v0.1.0`, GitHub release, update `boostopt.com`. Then apt: a `debian/` dir, `.deb` builds, and
a GPG-signed repository — a separate pipeline, likely using Nuitka's `--standalone --onefile` mode
so the package carries no Python dependency.

---

## 6. One-way doors

Things that cannot be undone. Each deserves a pause.

1. **Publishing the name.** Permanent. Yanking a version does not release the name.
2. **Publishing source.** If a wheel containing `.py` files is ever uploaded, that source is
   downloaded, cached, and mirrored within minutes. Deleting the release does not recall it.
3. **The licence you publish under.** You can change terms for future versions, but the version
   already published stays under the terms it shipped with.
4. **Installing Ollama via `--install-ollama`.** Not a PyPI matter, but the same shape: it puts a
   system service on a user's machine. `boostopt-uninstall --remove-ollama` reverses it.

---

## 7. Command index

| Task | Command |
|---|---|
| Full test suite | `pytest -q` |
| Fast loop | `pytest -q -m "not toolchain"` |
| Source wheel (rehearsal only) | `python -m build --wheel -o ../tmp/dist` |
| Compiled wheel | `python tools/build_native_wheel.py -o ../tmp/dist-native` |
| Validate metadata | `twine check ../tmp/dist/*` |
| TestPyPI | `twine upload --repository testpypi ../tmp/dist/*` |
| Real PyPI | `twine upload ../tmp/dist/*` |

After any wheel build: `git checkout -- build/ && git clean -fdq build/` — `build/` is tracked and
stale, and building rewrites it with unrelated drift.
