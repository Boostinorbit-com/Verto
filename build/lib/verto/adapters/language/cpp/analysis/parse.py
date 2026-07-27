"""libclang parse infrastructure — the shared base for AST analysis.

Owns: the translation-unit cache (`_tu`), the system-include discovery, the
thread-local per-TU flags (codebase mode parses TUs in parallel — item #8), error
diagnostics, and the pruned in-file walkers (`_funcs`/`_infile_records`) that skip
the ~99.8% of nodes that are system-header noise.
"""
from __future__ import annotations

import functools
import os
import subprocess
import threading

import clang.cindex as cc

# Per-translation-unit flags from compile_commands.json (-I/-D/-std/…), set by the
# Sensor before it parses. THREAD-LOCAL: codebase mode can process TUs in parallel
# (item #8), and each worker parses a different TU with different flags — a shared
# module global would race. Folded into the _tu cache key so TUs never collide.
_tls = threading.local()


def set_parse_args(flags: tuple[str, ...]) -> None:
    _tls.args = tuple(flags or ())


def _extra() -> tuple[str, ...]:
    return getattr(_tls, "args", ())


@functools.lru_cache(maxsize=1)
def _parse_args() -> list[str]:
    """Discover the system C++ include search paths from clang++ and pass them to
    libclang. A pip-bundled libclang ships no resource dir, so `#include <cstddef>`
    fails ('stddef.h not found') and types don't resolve; feeding it the real
    clang++'s search list (builtin + libstdc++) fixes that. Falls back to a bare
    -std if clang++ isn't reachable (a system libclang may find headers itself)."""
    args = ["-std=c++17", "-fPIC"]        # -fPIC: Qt/other headers #error without __PIC__
    try:
        out = subprocess.run(["clang++", "-E", "-x", "c++", "-v", "-"], input="",
                             capture_output=True, text=True, timeout=20).stderr
    except Exception:
        return args
    grab = False
    for line in out.splitlines():
        if "search starts here:" in line:
            grab = True
            continue
        if "End of search list." in line:
            break
        if grab:
            p = line.strip().split(" (framework")[0].strip()
            if p and os.path.isdir(p):
                args += ["-isystem", p]
    return args


@functools.lru_cache(maxsize=16)
def _tu(source: str, extra: tuple[str, ...] = ()):
    # cached: the sensor + mutator parse the same source several times per optimize.
    # `extra` = compile_commands flags (part of the key so per-TU flags don't collide).
    idx = cc.Index.create()
    return idx.parse("in.cpp", args=_parse_args() + list(extra),
                     unsaved_files=[("in.cpp", source)])


def parse_errors(source: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Error/fatal libclang diagnostics for a TU (deduped, capped) — so a parse
    failure that would otherwise be swallowed by a bare `except` becomes a logged
    skip reason instead of a silent 'nothing found' (Phase-1 item #4). Empty list
    when libclang is unavailable or the TU parses clean."""
    try:
        tu = _tu(source, tuple(extra) or _extra())   # same flags the detectors used
    except Exception as e:
        return [f"libclang parse failed: {type(e).__name__}"]
    out, seen = [], set()
    for d in tu.diagnostics:
        if d.severity >= cc.Diagnostic.Error:
            msg = d.spelling
            if msg not in seen:
                seen.add(msg)
                out.append(msg)
            if len(out) >= 5:
                break
    return out


def _walk(node):
    yield node
    for c in node.get_children():
        yield from _walk(c)


def _funcs(tu):
    """In-file function definitions. A translation unit is ~99.8% system-header
    nodes (a `#include <map>` alone brings ~50k), so we PRUNE header subtrees
    instead of walking the whole tree and filtering — the AST hot path. Only
    descends into in-file (or location-less builtin) nodes."""
    def infile(node):
        for c in node.get_children():
            lf = c.location.file
            if lf is not None and lf.name != "in.cpp":
                continue                                # skip the entire header subtree
            if (c.kind == cc.CursorKind.FUNCTION_DECL and c.is_definition()
                    and lf is not None and lf.name == "in.cpp"):
                yield c
            yield from infile(c)
    yield from infile(tu.cursor)


@functools.lru_cache(maxsize=16)
def _infile_funcs(source: str, extra: tuple[str, ...] = ()):
    """The in-file functions, walked ONCE per (source, flags). signature /
    all_growth / all_map each need them; without this they'd re-walk ~12×."""
    return tuple(_funcs(_tu(source, extra)))


def _infile_records(tu):
    """In-file struct/class definitions (header subtrees pruned — see _funcs)."""
    def rec(node):
        for c in node.get_children():
            lf = c.location.file
            if lf is not None and lf.name != "in.cpp":
                continue
            if c.kind in (cc.CursorKind.STRUCT_DECL, cc.CursorKind.CLASS_DECL) and c.is_definition():
                yield c
            yield from rec(c)
    yield from rec(tu.cursor)
