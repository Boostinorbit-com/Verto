"""compile_commands.json reader — the bridge from single files to real codebases.

A real project's translation units aren't self-contained: they need include
paths, defines and a language standard to even parse. `compile_commands.json`
(emitted by CMake `-DCMAKE_EXPORT_COMPILE_COMMANDS=ON`, Bazel, or `bear`) records
the exact compile command per file. We extract *only* the flags that tell the
parser/harness where headers live and which dialect to use — `-I/-isystem/-iquote/
-idirafter/-D/-U/-std/-isysroot` — and drop everything else (`-c`, `-o`, `-O`,
`-W`, `-g`, `-f…`, the source path). Those kept flags are safe for BOTH libclang
parsing and compiling VERTO's self-contained verification harness.

Scope (Level A): this lets VERTO PARSE real TUs and find/verify the functions its
harness generator can extract. It does NOT yet link against the project's other
object files — a function whose body calls into other TUs is honestly skipped
(verify-or-skip), same as always.
"""
from __future__ import annotations

import json
import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

_CPP_EXT = {".cpp", ".cc", ".cxx", ".c++", ".cp", ".C"}
_TWO_ARG = ("-I", "-isystem", "-iquote", "-idirafter", "-isysroot", "-D", "-U")
_PATH_FLAGS = ("-I", "-isystem", "-iquote", "-idirafter", "-isysroot")


@dataclass
class TU:
    file: str                       # absolute source path
    directory: str
    flags: list[str] = field(default_factory=list)   # -I/-D/-std/… for parse + harness


def _abs(directory: str, p: str) -> str:
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(directory, p))


def _extract_flags(tokens: list[str], directory: str) -> list[str]:
    flags: list[str] = []
    i, n = 1, len(tokens)                      # tokens[0] is the compiler
    while i < n:
        t = tokens[i]
        if t in _TWO_ARG:                      # separated form: "-I" "path" / "-D" "FOO"
            val = tokens[i + 1] if i + 1 < n else ""
            flags += [t, _abs(directory, val) if t in _PATH_FLAGS else val]
            i += 2
            continue
        if t.startswith("-I"):                 # joined form "-Ipath"
            flags.append("-I" + _abs(directory, t[2:]))
        elif t.startswith("-isystem"):
            flags.append("-isystem" + _abs(directory, t[len("-isystem"):]))
        elif t.startswith(("-D", "-U", "-std=")):
            flags.append(t)
        i += 1
    return flags


def _dedup(seq: list[str]) -> list[str]:
    out, seen = [], set()
    for x in seq:
        if x not in seen:
            seen.add(x); out.append(x)
    return out


def find(path: str) -> Path | None:
    """Resolve a user-given path to a compile_commands.json file (accepts the file
    itself, a directory holding it, or a directory with a build/ subdir)."""
    p = Path(path)
    if p.is_file():
        return p
    for cand in (p / "compile_commands.json", p / "build" / "compile_commands.json"):
        if cand.is_file():
            return cand
    return None


def load(path: str) -> list[TU]:
    """Parse compile_commands.json into a de-duplicated list of C++ translation units."""
    cc = find(path)
    if cc is None:
        raise ValueError(f"no compile_commands.json at {path}")
    data = json.loads(cc.read_text(encoding="utf-8"))
    base = cc.parent.resolve()
    tus, seen = [], set()
    for e in data:
        # CMake/Bazel emit an absolute `directory`; a relative one (portable
        # hand-written db) is resolved against the compile_commands.json itself.
        directory = e.get("directory") or str(base)
        if not os.path.isabs(directory):
            directory = os.path.normpath(os.path.join(base, directory))
        f = e.get("file")
        if not f:
            continue
        af = _abs(directory, f)
        if af in seen or Path(af).suffix not in _CPP_EXT:
            continue
        seen.add(af)
        toks = e.get("arguments") or (shlex.split(e["command"]) if e.get("command") else [])
        tus.append(TU(file=af, directory=directory, flags=_dedup(_extract_flags(toks, directory))))
    return tus
