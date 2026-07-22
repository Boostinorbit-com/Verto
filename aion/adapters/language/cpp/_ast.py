"""Robust AST-based detection via libclang (build step 5).

Replaces the regex heuristics (_detect.py) with real type resolution and scope
analysis: it knows a variable's *actual* type, which function it's in, and
whether a call is a member call on it — none of which regex can do reliably.

Returns the same GrowthSite / MapSite dataclasses (with source offsets) as the
regex path, so the Mutator/transforms are unchanged. `_detect.py` prefers this
and falls back to regex if libclang is unavailable or finds nothing.
"""
from __future__ import annotations

import functools
import os
import subprocess

import clang.cindex as cc

from ._detect import GrowthSite, MapSite


@functools.lru_cache(maxsize=1)
def _parse_args() -> list[str]:
    """Discover the system C++ include search paths from clang++ and pass them to
    libclang. A pip-bundled libclang ships no resource dir, so `#include <cstddef>`
    fails ('stddef.h not found') and types don't resolve; feeding it the real
    clang++'s search list (builtin + libstdc++) fixes that. Falls back to a bare
    -std if clang++ isn't reachable (a system libclang may find headers itself)."""
    args = ["-std=c++17"]
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


@functools.lru_cache(maxsize=8)
def _tu(source: str):
    # cached: the sensor + mutator parse the same source several times per optimize.
    idx = cc.Index.create()
    return idx.parse("in.cpp", args=_parse_args(), unsaved_files=[("in.cpp", source)])


def _walk(node):
    yield node
    for c in node.get_children():
        yield from _walk(c)


def _funcs(tu):
    for n in _walk(tu.cursor):
        if n.kind == cc.CursorKind.FUNCTION_DECL and n.is_definition() and n.location.file:
            if n.location.file.name == "in.cpp":       # skip anything from headers
                yield n


def _is_call_on(call, var: str, method: str) -> bool:
    toks = [t.spelling for t in call.get_tokens()]
    return len(toks) >= 3 and toks[0] == var and toks[1] == "." and toks[2] == method


def _for_bound(for_stmt) -> str | None:
    for c in for_stmt.get_children():
        if c.kind == cc.CursorKind.BINARY_OPERATOR:
            toks = [t.spelling for t in c.get_tokens()]
            if "<" in toks:
                i = toks.index("<")
                return toks[i + 1] if i + 1 < len(toks) else None
    return None


def _template_arg(ctype, i: int) -> str:
    try:
        if ctype.get_num_template_arguments() > i:
            return ctype.get_template_argument_type(i).spelling
    except Exception:
        pass
    s = ctype.spelling
    inner = s[s.find("<") + 1:s.rfind(">")] if "<" in s else ""
    parts, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "<":
            depth += 1
        elif ch == ">":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts[i].strip() if i < len(parts) else ""


def _b2c(source: str, byte_off: int) -> int:
    """libclang reports UTF-8 BYTE offsets; Python str indexes by codepoint.
    Convert so splicing is correct when the source contains multi-byte chars."""
    return len(source.encode("utf-8")[:byte_off].decode("utf-8", "ignore"))


def _stmt_end(source: str, node) -> int:
    # anchor on the declared-name location, then the next ';' terminates the decl.
    # (the VAR_DECL extent can over-run into trailing comments / the next stmt.)
    start = _b2c(source, node.location.offset)
    semi = source.find(";", start)
    return semi + 1 if semi != -1 else start


def _growth_in_fn(fn, source: str) -> GrowthSite | None:
    nodes = list(_walk(fn))
    calls = [c for c in nodes if c.kind == cc.CursorKind.CALL_EXPR]
    fors = [c for c in nodes if c.kind == cc.CursorKind.FOR_STMT]
    for v in nodes:
        if v.kind != cc.CursorKind.VAR_DECL or not v.type.spelling.startswith("std::vector"):
            continue
        var = v.spelling
        if any(_is_call_on(c, var, "reserve") for c in calls):
            continue                                        # already reserved
        for fs in fors:
            fcalls = [c for c in _walk(fs) if c.kind == cc.CursorKind.CALL_EXPR]
            if any(_is_call_on(c, var, "push_back") or _is_call_on(c, var, "emplace_back")
                   for c in fcalls):
                return GrowthSite(func=fn.spelling, var=var, bound=_for_bound(fs),
                                  insert_at=_stmt_end(source, v),
                                  elem_type=_template_arg(v.type, 0))
    return None


def all_growth(source: str) -> list[GrowthSite]:
    tu = _tu(source)
    return [s for fn in _funcs(tu) if (s := _growth_in_fn(fn, source))]


def growth_ast(source: str) -> GrowthSite | None:
    sites = all_growth(source)
    return sites[0] if sites else None


def growth_in_ast(source: str, func: str) -> GrowthSite | None:
    return next((s for s in all_growth(source) if s.func == func), None)


def _std_map_offset(cursor, source: str) -> int | None:
    """Offset of the `std::map` type text in this declaration, via the TEMPLATE_REF
    child cursor (which points at the `map` template name)."""
    for ch in cursor.get_children():
        if ch.kind == cc.CursorKind.TEMPLATE_REF and ch.spelling == "map":
            s = _b2c(source, ch.extent.start.offset - len("std::"))   # byte→char, back up over "std::"
            if source[s:s + len("std::map")] == "std::map":
                return s
    return None


def _map_in_fn(fn, source: str) -> MapSite | None:
    for v in _walk(fn):
        if v.kind == cc.CursorKind.VAR_DECL and v.type.spelling.startswith("std::map"):
            ts = _std_map_offset(v, source)
            if ts is None:
                continue
            return MapSite(func=fn.spelling, var=v.spelling,
                           key=_template_arg(v.type, 0), val=_template_arg(v.type, 1),
                           type_start=ts, type_end=ts + len("std::map"))
    return None


def all_map(source: str) -> list[MapSite]:
    tu = _tu(source)
    return [s for fn in _funcs(tu) if (s := _map_in_fn(fn, source))]


def map_ast(source: str) -> MapSite | None:
    sites = all_map(source)
    return sites[0] if sites else None


def map_in_ast(source: str, func: str) -> MapSite | None:
    return next((s for s in all_map(source) if s.func == func), None)
