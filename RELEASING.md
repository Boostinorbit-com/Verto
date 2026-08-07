# Releasing BOOSTOPT

> ⛔ **PUBLIC RELEASE IS ON HOLD.** BOOSTOPT is currently **proprietary / all rights reserved** (see `LICENSE`) while pre-launch, to keep every future licensing option open. `pyproject.toml` carries the `Private :: Do Not Upload` classifier, which makes **PyPI reject any upload** — a deliberate guard. The steps below are the *intended* flow for **if/when** an open-source core is published under a chosen license; do not run the `twine upload` steps until that decision is made.

BOOSTOPT would ship as **`boostopt`** on PyPI (the import + CLI stay `boostopt`) and as a Docker image.
Do this on **Python 3.11+** (the package's floor).

## 1. Pre-flight
- [ ] CI is green on `main` (tests + wedge).
- [ ] Bump `version` in `pyproject.toml` (semver; `0.1.0` → `0.1.1` / `0.2.0`).
- [ ] `README.md` quickstart still runs.

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
- **`boostopt` vs `boostopt`:** the distribution name is `boostopt` (the plain `boostopt` was taken); the package you `import` and the command you run are both `boostopt`.
- **System deps aren't pip-installable:** `clang++`/sanitizers must be present on the user's machine (or use the Docker image). `boostopt analyze --verify-setup` reports what's missing.
