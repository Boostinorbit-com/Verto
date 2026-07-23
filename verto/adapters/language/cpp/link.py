"""Project archive builder — link the verification harness against the real build.

Phase-1 item #1 (VERTO_Roadmap §4). The harness embeds the target TU's full
source + a driver main(), but a function that calls into OTHER translation units
leaves those symbols undefined → the link fails → VERTO can't verify it. Here we
compile every OTHER project TU (from compile_commands.json) to an object, `ar`
them into a static archive, and hand that archive to the harness link step.

Why an archive (not loose .o files): archive members are pulled ON DEMAND — the
linker extracts only the members needed to resolve the harness's undefined
symbols. So the project's own main()/globals never collide with the driver, and
the link stays minimal.

Why the target TU is EXCLUDED: the harness already embeds its full source (that
is where the *variant* body under test lives); a second copy from the archive
would be a duplicate-symbol error.

Two-tier content-addressed cache:
  * per-TU objects  — keyed on (source bytes + flags); shared across every target
    and every run (this is the expensive part, compiled once).
  * per-target archive — a cheap `ar` over the cached objects, keyed on the set of
    member objects it contains.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from pathlib import Path

from ....runtime import sandbox

CXX = "clang++"
_OBJ_DIR = Path(tempfile.gettempdir()) / "verto-obj"
_ARC_DIR = Path(tempfile.gettempdir()) / "verto-archive"


def _obj_flags(tu_flags: list[str]) -> list[str]:
    """Flags to compile ONE other-TU to an object. We only need it to *compile*
    (never to link standalone), so the parse/harness flags (-I/-D/-std) plus -O2
    are enough; a -std is forced if the db didn't record one, to keep the ABI in
    line with the c++20 harness."""
    flags = list(tu_flags)
    if not any(f.startswith("-std=") for f in flags):
        flags.append("-std=c++20")
    flags.append("-O2")
    return flags


def _atomic_store(tmp: str, final: Path) -> str | None:
    if not os.path.exists(tmp):
        return None
    try:
        os.replace(tmp, final)                    # atomic; safe under concurrency
        return str(final)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None


def _compile_object(source_path: str, flags: list[str]) -> str | None:
    """Compile one TU to a cached object (-c only). Returns the object path, or
    None if the source is unreadable or the compile fails — a TU that won't
    compile simply doesn't contribute symbols (the link may then skip-not-reject)."""
    try:
        src_bytes = Path(source_path).read_bytes()
    except OSError:
        return None
    key = hashlib.sha1(src_bytes + b"\0" + "\0".join(flags).encode("utf-8")).hexdigest()
    _OBJ_DIR.mkdir(exist_ok=True)
    obj = _OBJ_DIR / f"{key}.o"
    if obj.exists():
        return str(obj)
    tmp = f"{obj}.{os.getpid()}.{threading.get_ident()}.tmp"   # thread-unique (item #8)
    r = sandbox.run([CXX, *flags, "-c", source_path, "-o", tmp], timeout_sec=120)
    if not r.ok:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None
    return _atomic_store(tmp, obj)


def project_archive(tus, target_file: str) -> str | None:
    """Build (cached) a static archive of every project TU EXCEPT target_file.

    Returns the archive path to add to the harness link step, or None when there
    is nothing to link (single-TU project) or no object could be built."""
    target = os.path.realpath(target_file)
    members: list[str] = []
    for tu in tus:
        if os.path.realpath(tu.file) == target:
            continue
        obj = _compile_object(tu.file, _obj_flags(tu.flags))
        if obj is not None:
            members.append(obj)
    if not members:
        return None
    members.sort()                                # stable archive identity
    akey = hashlib.sha1("\0".join(members).encode("utf-8")).hexdigest()
    _ARC_DIR.mkdir(exist_ok=True)
    arc = _ARC_DIR / f"{akey}.a"
    if arc.exists():
        return str(arc)
    tmp = f"{arc}.{os.getpid()}.{threading.get_ident()}.tmp"   # thread-unique (item #8)
    r = sandbox.run(["ar", "rcs", tmp, *members], timeout_sec=120)
    if not r.ok:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return None
    return _atomic_store(tmp, arc)
