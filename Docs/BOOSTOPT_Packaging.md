# Packaging BOOSTOPT — closed-source distribution

BOOSTOPT ships under a commercial EULA (`LICENSE`), and the engine is not published anywhere.
A licence governs what people may *legally* do; it does nothing about what they can *see*. This
document is about the second half.

## The problem: a pure-Python wheel ships your source

A `py3-none-any` wheel is a zip of `.py` files. Measured on the real artifact:

```
$ python -c "import zipfile; print(len([n for n in zipfile.ZipFile('boostopt-0.1.0-py3-none-any.whl').namelist() if n.endswith('.py')]))"
80
```

That includes `boostopt/engine/gate.py` — the trusted core, the only place in the codebase that
returns `accepted=True`. Anyone can `pip download boostopt` and read it. **`.pyc`-only shipping
is not a fix**: `pycdc` and similar reconstruct readable source, and you lose tracebacks.

## The approach: compile to a native extension (Nuitka)

```bash
python -m nuitka --module boostopt --include-package=boostopt --output-dir=dist-native
```

Produces one `boostopt.cpython-311-x86_64-linux-gnu.so` (~4.1 MB). Verified:

| Check | Result |
|---|---|
| `boostopt.__compiled__` | `True` (loader: `nuitka_module_loader`) |
| `.py` files on disk | **0** |
| `boostopt demo` from the binary alone | ACCEPT, −66.7% p50, Rung 3 clean |

`__file__` still reports a `.py` path — Nuitka synthesises it. Don't use that to test whether a
build is compiled; use `__compiled__`.

## What broke, and why it will break again if you undo it

The first compiled build silently lost its data files. `importlib.resources` has no filesystem
package to read once everything is one `.so`, so:

```
Modelfile : False | base: None        # boostopt init downgrades to the bare base model
demo      : False                     # boostopt demo cannot find its sample
```

Neither raised — they returned "not found", which the code treats as "not one of ours". A
pure-Python test run passes completely while the shipped artifact is broken.

**Fix: assets are module constants, not package data.**

- `boostopt/runtime/models/__init__.py` → `MODELFILES: dict[str, str]`
- `boostopt/examples/__init__.py` → `DEMO_NAME`, `DEMO_SOURCE`

`provision.bundled_modelfile()` writes the text to a temp file when `ollama create -f` needs a
path. There is no `[tool.setuptools.package-data]` section at all any more, which also removes
the class of bug where a glob is forgotten and the file exists in a checkout but not the wheel.

Guarded by `tests/invariants/test_boundary.py`:
`test_runtime_assets_are_module_constants_not_data_files` and
`test_no_stray_data_files_left_inside_the_package`.

## Remaining work before compiled wheels ship

1. **A build matrix.** `py3-none-any` becomes platform- and version-specific: manylinux
   x86_64/aarch64, macOS x86_64/arm64, Windows, times CPython 3.11/3.12/3.13 — roughly 9–12
   wheels per release. Use `cibuildwheel`; Nuitka runs inside each matrix job.
2. **Console scripts.** `boostopt` and `boostopt-uninstall` are entry points resolved from
   package metadata; confirm they still resolve against a compiled module in each target.
3. **`boostopt_server` stays out**, as today — see the open-core boundary tests.
4. **Tracebacks.** Compiled frames report synthetic paths; decide whether crash reports need a
   symbol map kept privately.
5. **Build time.** ~10 minutes for 84 C files with a cold ccache; budget for it in CI.

## What compilation does and does not buy

It raises the cost of reading the engine from "unzip" to "reverse-engineer a stripped binary".
It is not DRM and it does not stop a determined competitor. The enforceable protection is the
EULA; compilation is the practical deterrent. Weigh that against the matrix cost — a plausible
alternative is shipping readable Python under the same EULA and competing on brand, support,
and the hosted tier.
