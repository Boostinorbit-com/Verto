# Publishing BOOSTOPT to PyPI — a runbook

Copy-pasteable steps, in order. Run everything from the repo root with `.venv` active.
Scratch artifacts go to `../tmp/` (never `/tmp`).

Related: `RELEASING.md` (release policy + tagging), `Docs/BOOSTOPT_Packaging.md` (closed-source
compiled builds).

---

## 0. Decide these first — they are not technical

| Decision | Status | Why it blocks |
|---|---|---|
| **Licence** | EULA drafted in `LICENSE`, **unreviewed** | It has `[DECIDE]` / `[JURISDICTION]` placeholders and no legal review. Publishing binds you to it. |
| **Source visibility** | undecided | A normal wheel ships 80 readable `.py` files, including `engine/gate.py`. If that is unacceptable, §5 is your path, not §3. |
| **Repo visibility** | `Repository`/`Issues` point at GitHub | If that repo is private, every sidebar link on your PyPI page 404s. |

`boostopt` was free on PyPI as of 2026-08-09 (`https://pypi.org/simple/boostopt/` → 404).
**Re-check before uploading** — names can be claimed at any time, and PyPI normalises
`boost-opt`, `boost_opt`, and `BoostOpt` to the same name.

---

## 1. Accounts (one-time)

1. Register at <https://pypi.org/account/register/> **and** <https://test.pypi.org/account/register/>
   — they are separate accounts; credentials do not carry over.
2. Enable 2FA on both. It is mandatory for uploading. **Save the recovery codes** — losing 2FA on
   the account that owns your package name is a painful recovery.
3. Get an upload credential. Either:
   - **API token** — username `__token__`, password `pypi-…`. The first one must be account-wide
     because the project does not exist yet; scope it to the project after the first upload.
   - **Trusted Publishing** (preferred) — GitHub Actions authenticates via OIDC, so no long-lived
     secret is stored anywhere. Configure it on PyPI against the repo, workflow file, and
     environment.

Registering an account does **not** reserve the name. Only a successful upload does.

---

## 2. Pre-flight

```bash
pytest -q                                   # expect 236 passed, 3 skipped
./check.sh                                  # end-to-end engine self-check
python -m pytest -q -m "not toolchain"      # 8s sanity loop
```

- [ ] Suite green (a lone `toolchain` failure is usually the known flake — re-run before investigating)
- [ ] `version` in `pyproject.toml` bumped
- [ ] `LICENSE` reviewed by counsel, placeholders resolved
- [ ] `Repository` / `Issues` URLs resolve for a logged-out visitor
- [ ] `boostopt` still free on PyPI

---

## 3. Build the wheel

**Wheel only.** `python -m build` with no flags also produces a `.tar.gz` sdist, which is your
entire source tree. Uploading that publishes everything regardless of licence.

```bash
pip install build twine
python -m build --wheel -o ../tmp/dist && git checkout -- build/ && git clean -fdq build/
```

The `git checkout -- build/` is not optional: `build/` is tracked but stale, and building
rewrites a dozen files with unrelated drift.

```bash
twine check ../tmp/dist/*
```

### Inspect exactly what you are about to publish

```bash
python -c "
import zipfile, glob
z = zipfile.ZipFile(glob.glob('../tmp/dist/*.whl')[0]); n = z.namelist()
print('wheel       :', z.filename.split('/')[-1])
print('.py files   :', len([x for x in n if x.endswith('.py')]))
print('server leak :', [x for x in n if x.startswith('boostopt_server')] or 'none')
md = z.read([x for x in n if x.endswith('METADATA')][0]).decode()
for k in ('License-Expression','License-File','Project-URL','Requires-Dist'):
    print(f'{k:18}', [l for l in md.splitlines() if l.startswith(k)])"
```

Expect `server leak: none` — `boostopt_server` is the proprietary tier and must never ship
(guarded by `tests/invariants/test_boundary.py`).

---

## 4. TestPyPI rehearsal

```bash
twine upload --repository testpypi ../tmp/dist/*
```

Verify from a clean venv — the `--extra-index-url` is needed because TestPyPI does not mirror
`libclang`:

```bash
python -m venv ../tmp/verify
../tmp/verify/bin/pip install -i https://test.pypi.org/simple/ \
    --extra-index-url https://pypi.org/simple/ boostopt
../tmp/verify/bin/boostopt demo
../tmp/verify/bin/boostopt analyze --verify-setup
```

`boostopt demo` is the real test: it compiles, differential-tests, sanitises, and benchmarks real
C++ from a bare install. An import smoke test would not catch a missing asset.

---

## 5. Closed-source release (if the engine must not be readable)

§3 ships readable Python. If that is unacceptable, the wheel must be built from compiled
extension modules — see `Docs/BOOSTOPT_Packaging.md` for the verified Nuitka process. Not yet
built:

1. **Platform tagging.** A wheel containing a `.so` must be tagged
   `cp311-cp311-manylinux_2_17_x86_64`, not `py3-none-any`, or pip installs a Linux binary on
   macOS and it fails at import.
2. **A build matrix.** ~9–12 wheels per release (manylinux x86_64/aarch64, macOS x86_64/arm64,
   Windows × CPython 3.11/3.12/3.13). Use `cibuildwheel`, with Nuitka inside each job.
3. **No sdist, ever** — it would ship the source you just compiled away.

Until that exists, §3 + §4 are a rehearsal, not a release.

---

## 6. Publish

```bash
twine upload ../tmp/dist/*
```

This claims the name permanently. PyPI allows yanking a version but never reuses or releases a
project name.

```bash
python -m venv ../tmp/final
../tmp/final/bin/pip install boostopt
../tmp/final/bin/boostopt demo
```

---

## 7. Tag and announce

```bash
git tag -a v0.1.0 -m "BOOSTOPT v0.1.0"
git push --tags
```

Create a GitHub Release from the tag with the changelog. Update `boostopt.com` and
`install.sh` if the install instructions changed.

---

## 8. Clean up

```bash
rm -rf ../tmp/dist ../tmp/verify ../tmp/final
```

---

## Troubleshooting — things that actually happened

| Symptom | Cause | Fix |
|---|---|---|
| `boostopt is already installed with the same version` | pip sees `boostopt.egg-info` in the repo root and thinks it is installed | run pip from a different cwd, or `--force-reinstall` |
| A dozen unrelated files modified after a build | `build/` is tracked and stale | `git checkout -- build/ && git clean -fdq build/` |
| `No matching distribution found for setuptools>=77` | build env is Python 3.8; setuptools 77 dropped 3.8 | build on 3.11+ |
| Wheel installs but `boostopt demo` says file not found | an asset became package data again instead of a module constant | see `Docs/BOOSTOPT_Packaging.md`; `tests/invariants` guards this |
| `compiled: False` when testing a Nuitka build | run from a directory where `boostopt/` source is importable | `cd` into the directory holding only the `.so` |
