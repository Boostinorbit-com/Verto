# Releasing VERTO

VERTO ships as **`verto-optimizer`** on PyPI (the import + CLI stay `verto`) and as a Docker image.
Do this on **Python 3.11+** (the package's floor).

## 1. Pre-flight
- [ ] CI is green on `main` (tests + wedge).
- [ ] Bump `version` in `pyproject.toml` (semver; `0.1.0` → `0.1.1` / `0.2.0`).
- [ ] `README.md` quickstart still runs.

## 2. Build + check the artifacts
```bash
python -m pip install --upgrade build twine
python -m build                 # → dist/verto_optimizer-<v>.tar.gz + .whl
twine check dist/*              # validates the metadata renders on PyPI
```

## 3. Publish to TestPyPI first (dry run)
```bash
twine upload --repository testpypi dist/*
# verify it installs from there, in a clean venv:
pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ verto-optimizer
verto analyze --verify-setup
```

## 4. Publish to PyPI
```bash
twine upload dist/*             # uses ~/.pypirc or a PYPI_TOKEN
```
Then confirm: `pip install verto-optimizer` in a fresh venv → `verto optimize examples/packet_stats.cpp --offline`.

## 5. Tag the release
```bash
git tag -a v<version> -m "VERTO v<version>"
git push --tags
```
Create a GitHub Release from the tag with the changelog.

## 6. Docker image (optional)
```bash
docker build -t <registry>/verto:<version> -t <registry>/verto:latest .
docker push <registry>/verto:<version> && docker push <registry>/verto:latest
```

## Notes
- **Credentials:** use a scoped **PyPI API token** (`__token__` / `pypi-…`), not a password. Store it in `~/.pypirc` or CI secrets — never commit it.
- **`verto` vs `verto-optimizer`:** the distribution name is `verto-optimizer` (the plain `verto` was taken); the package you `import` and the command you run are both `verto`.
- **System deps aren't pip-installable:** `clang++`/sanitizers must be present on the user's machine (or use the Docker image). `verto analyze --verify-setup` reports what's missing.
