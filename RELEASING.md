# Releasing BOOSTOPT

> **Licence:** BOOSTOPT ships under its own commercial EULA (`LICENSE`), not an open-source
> licence. Proprietary packages are perfectly publishable on PyPI. The blocking question is no
> longer *may we upload* but *have the EULA and the third-party NOTICE been reviewed by counsel* —
> see the pre-flight list.
>
> **Source visibility:** a pure-Python wheel ships readable `.py`. If the engine must stay closed,
> the wheel has to be built from compiled extension modules first — see `Docs/BOOSTOPT_Packaging.md`.

> **Step-by-step commands:** `Docs/BOOSTOPT_Publishing.md` is the runbook — accounts, build, TestPyPI rehearsal, upload, and the traps. This file is the policy; that one is the procedure.

BOOSTOPT would ship as **`boostopt`** on PyPI (the import + CLI stay `boostopt`) and as a Docker image.
Do this on **Python 3.11+** (the package's floor).

## 1. Pre-flight
- [ ] CI is green on `main` (tests + wedge).
- [ ] Bump `version` in `pyproject.toml` (semver; `0.1.0` → `0.1.1` / `0.2.0`).
- [ ] `README.md` quickstart still runs — **from a pip install, not the repo.** The repo-root
      `examples/` is not packaged, so verify with `boostopt demo` in a clean venv; anything the
      quickstart references must be either bundled or created by the command itself.
- [ ] The `Repository`/`Issues` URLs resolve for a logged-out visitor (a private GitHub repo
      404s on every PyPI sidebar link).
- [ ] `boostopt` is free on PyPI, or the name is settled (see Notes).
- [ ] Decide the licence. `Private :: Do Not Upload` must be removed to publish, and PyPI serves
      readable Python source to anyone — publishing is the moment "proprietary" stops meaning
      "unavailable". `license = "LicenseRef-Proprietary"` should become a real SPDX id if an open
      core is chosen.

## 2. Build + check the artifacts
```bash
python -m pip install --upgrade build twine
python -m build                 # → dist/boostopt-<v>.tar.gz + .whl
twine check dist/*              # validates the metadata renders on PyPI
```

## 3. Publish to TestPyPI first (dry run)
```bash
twine upload --repository testpypi dist/*
# verify it installs from there, in a clean venv:
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ boostopt
boostopt analyze --verify-setup
```

## 4. Publish to PyPI
```bash
twine upload dist/*             # uses ~/.pypirc or a PYPI_TOKEN
```
Then confirm: `pip install boostopt` in a fresh venv → `boostopt optimize examples/packet_stats.cpp --offline`.

## 5. Tag the release
```bash
git tag -a v<version> -m "BOOSTOPT v<version>"
git push --tags
```
Create a GitHub Release from the tag with the changelog.

## 6. Docker image (optional)
```bash
docker build -t <registry>/boostopt:<version> -t <registry>/boostopt:latest .
docker push <registry>/boostopt:<version> && docker push <registry>/boostopt:latest
```

## Notes
- **Credentials:** use a scoped **PyPI API token** (`__token__` / `pypi-…`), not a password. Store it in `~/.pypirc` or CI secrets — never commit it.
- **The name:** distribution, import package, and command are all `boostopt` — no split. **Free on PyPI as of 2026-08-09**: `https://pypi.org/simple/boostopt/` returns 404, which for the simple index means the name is unregistered (it is served for any registered project, even one with zero releases). Re-check before uploading — names can be claimed at any time, and PyPI normalizes `boost-opt`/`boost_opt`/`BoostOpt` to the same name.
  (The line here previously read "`boostopt` vs `boostopt` … the plain one was taken" — a Veritoz-era note comparing two different names, left mangled by the rename and untrue of the current one.)
- **System deps aren't pip-installable:** `clang++`/sanitizers must be present on the user's machine (or use the Docker image). `boostopt analyze --verify-setup` reports what's missing.
