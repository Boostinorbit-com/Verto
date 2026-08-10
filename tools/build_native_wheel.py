#!/usr/bin/env python3
"""Build a CLOSED-SOURCE wheel: Nuitka-compiled `.so`, correctly platform-tagged.

`python -m build` produces `boostopt-<v>-py3-none-any.whl` containing ~80 readable `.py` files,
including `engine/gate.py`. For a proprietary release that is the wrong artifact. This script
produces the right one:

    1. build the normal wheel  → correct METADATA, entry_points, licence files
    2. compile with Nuitka     → one boostopt.cpython-3XX-<plat>.so, no source
    3. swap the payload        → dist-info kept verbatim, `boostopt/` tree replaced by the .so
    4. retag                   → cp311-cp311-linux_x86_64, NOT py3-none-any

Step 4 is not cosmetic. A wheel carrying a compiled extension but tagged `py3-none-any` is
installable on every platform, and fails at import on all but the one it was built for — a
runtime error on the user's machine that no build-time check would catch.

    python tools/build_native_wheel.py -o ../tmp/dist-native

On Linux the result is tagged `linux_x86_64`, which **PyPI rejects**. Run `auditwheel repair`
(needs patchelf) to convert it to a `manylinux_*` tag, or build inside a manylinux container —
which is what the release workflow does. The script tells you when that step is outstanding.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import sysconfig
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = "boostopt"


def run(argv: list[str], **kw) -> None:
    print(f"  $ {' '.join(argv[:6])}{' …' if len(argv) > 6 else ''}", flush=True)
    subprocess.run(argv, check=True, **kw)


def interpreter_tag() -> tuple[str, str, str]:
    """(python, abi, platform) for THIS interpreter, e.g. ('cp311','cp311','linux_x86_64')."""
    impl = "cp" if sys.implementation.name == "cpython" else sys.implementation.name[:2]
    ver = f"{sys.version_info.major}{sys.version_info.minor}"
    plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
    return f"{impl}{ver}", f"{impl}{ver}", plat


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--outdir", default="../tmp/dist-native")
    ap.add_argument("--keep-build", action="store_true", help="keep Nuitka's intermediate C")
    args = ap.parse_args()

    out = (ROOT / args.outdir).resolve()
    work = out / "_work"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)

    py, abi, plat = interpreter_tag()
    print(f"\n== target: {py}-{abi}-{plat}\n")

    # 1. the pure-Python wheel — we want its metadata, not its payload -------
    print("== 1/4  building the source wheel (for its metadata)")
    run([sys.executable, "-m", "pip", "wheel", str(ROOT), "--no-deps",
         "--no-build-isolation", "-q", "-w", str(work / "src")])
    src_whl = next((work / "src").glob("*.whl"))

    # 2. compile ------------------------------------------------------------
    print("\n== 2/4  compiling with Nuitka (several minutes)")
    run([sys.executable, "-m", "nuitka", "--module", PKG, f"--include-package={PKG}",
         f"--output-dir={work / 'nuitka'}", "--assume-yes-for-downloads", "--no-progressbar"],
        cwd=ROOT)
    so = next((work / "nuitka").glob(f"{PKG}.*.so"), None) or \
        next((work / "nuitka").glob(f"{PKG}.*.pyd"))
    (ROOT / f"{PKG}.pyi").unlink(missing_ok=True)     # Nuitka drops this beside the SOURCE

    # 3. swap the payload ---------------------------------------------------
    print("\n== 3/4  assembling the compiled wheel")
    stage = work / "stage"
    with zipfile.ZipFile(src_whl) as z:
        z.extractall(stage)
    shutil.rmtree(stage / PKG)                        # every .py goes
    shutil.copy2(so, stage / so.name)

    dist_info = next(stage.glob("*.dist-info"))
    wheel_meta = dist_info / "WHEEL"
    # WHEEL is RFC822: a BLANK LINE ENDS THE HEADERS. setuptools leaves a trailing one, so an
    # appended `Tag:` lands in the body and is silently ignored — `wheel pack` then fails with
    # "No tags present … cannot determine target wheel filename". Drop blanks before rebuilding.
    lines = [ln for ln in wheel_meta.read_text(encoding="utf-8").splitlines()
             if ln.strip() and not ln.startswith(("Tag:", "Root-Is-Purelib:"))]
    lines.insert(1, "Root-Is-Purelib: false")         # it is platlib now, not purelib
    lines.append(f"Tag: {py}-{abi}-{plat}")
    wheel_meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (dist_info / "RECORD").unlink(missing_ok=True)    # `wheel pack` regenerates it

    run([sys.executable, "-m", "wheel", "pack", str(stage), "-d", str(out)])
    built = max(out.glob("*.whl"), key=lambda p: p.stat().st_mtime)

    # 4. verify -------------------------------------------------------------
    print("\n== 4/4  verifying")
    with zipfile.ZipFile(built) as z:
        names = z.namelist()
    pys = [n for n in names if n.endswith(".py")]
    sos = [n for n in names if n.endswith((".so", ".pyd"))]
    leak = [n for n in names if n.startswith("boostopt_server")]
    ok = not pys and len(sos) == 1 and not leak

    print(f"   wheel        : {built.name}")
    print(f"   .py files    : {len(pys)}  {'OK' if not pys else 'LEAK: ' + str(pys[:3])}")
    print(f"   extension    : {sos[0] if sos else 'MISSING'}")
    print(f"   server leak  : {leak or 'none'}")
    if not args.keep_build:
        shutil.rmtree(work, ignore_errors=True)

    if plat.startswith("linux") and "manylinux" not in plat:
        print("\n   NOTE: tagged 'linux_x86_64' — PyPI REJECTS this. Run:")
        print(f"         auditwheel repair {built} -w {out}      (needs patchelf)")
        print("         or build inside a manylinux container (see the release workflow).")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
