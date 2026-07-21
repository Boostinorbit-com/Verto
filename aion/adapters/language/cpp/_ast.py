"""Robust AST-based detection via libclang (build step 5).

Replaces the regex heuristics (_detect.py) with real type resolution and scope
analysis: it knows a variable's *actual* type, which function it's in, and
whether a call is a member call on it — none of which regex can do reliably.

Returns the same GrowthSite / MapSite dataclasses (with source offsets) as the
regex path, so the Mutator/transforms are unchanged. `_detect.py` prefers this
and falls back to regex if libclang is unavailable or finds nothing.
"""
from __future__ import annotations

import clang.cindex as cc

from ._detect import GrowthSite, MapSite

_ARGS = ["-std=c++17"]


def _tu(source: str):
    idx = cc.Index.create()
    return idx.parse("in.cpp", args=_ARGS, unsaved_files=[("in.cpp", source)])


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


def _stmt_end(source: str, node) -> int:
    end = node.extent.end.offset
    semi = source.find(";", end)
    return semi + 1 if semi != -1 else end


def growth_ast(source: str) -> GrowthSite | None:
    tu = _tu(source)
    for fn in _funcs(tu):
        nodes = list(_walk(fn))
        calls = [c for c in nodes if c.kind == cc.CursorKind.CALL_EXPR]
        fors = [c for c in nodes if c.kind == cc.CursorKind.FOR_STMT]
        for v in nodes:
            if v.kind != cc.CursorKind.VAR_DECL or not v.type.spelling.startswith("std::vector"):
                continue
            var = v.spelling
            if any(_is_call_on(c, var, "reserve") for c in calls):
                continue                                    # already reserved
            for fs in fors:
                fcalls = [c for c in _walk(fs) if c.kind == cc.CursorKind.CALL_EXPR]
                if any(_is_call_on(c, var, "push_back") or _is_call_on(c, var, "emplace_back")
                       for c in fcalls):
                    return GrowthSite(func=fn.spelling, var=var, bound=_for_bound(fs),
                                      insert_at=_stmt_end(source, v),
                                      elem_type=_template_arg(v.type, 0))
    return None


def _std_map_offset(cursor, source: str) -> int | None:
    """Offset of the `std::map` type tokens in this declaration (robust to where
    libclang places the VAR_DECL extent start)."""
    toks = list(cursor.get_tokens())
    for i in range(len(toks) - 2):
        if (toks[i].spelling == "std" and toks[i + 1].spelling == "::"
                and toks[i + 2].spelling == "map"):
            ts = toks[i].extent.start.offset
            if source[ts:ts + len("std::map")] == "std::map":
                return ts
    return None


def map_ast(source: str) -> MapSite | None:
    tu = _tu(source)
    for fn in _funcs(tu):
        for v in _walk(fn):
            if v.kind == cc.CursorKind.VAR_DECL and v.type.spelling.startswith("std::map"):
                ts = _std_map_offset(v, source)
                if ts is None:
                    continue
                return MapSite(func=fn.spelling, var=v.spelling,
                               key=_template_arg(v.type, 0), val=_template_arg(v.type, 1),
                               type_start=ts, type_end=ts + len("std::map"))
    return None
