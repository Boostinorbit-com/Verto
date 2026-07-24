"""AST-based optimization-site detection — the robust replacement for the regex
heuristics (`regex_detect.py`). Knows a variable's *actual* type, which function
it's in, and whether a call is a member call on it.

Returns the same `GrowthSite` / `MapSite` dataclasses (with source offsets) as the
regex path, so the Mutator/transforms are unchanged. Three site kinds:
  * vector grown by push_back/emplace_back in a loop with no reserve()  (GrowthSite)
  * std::string grown by +=/append/push_back in a loop with no reserve() (GrowthSite)
  * std::map that could be std::unordered_map                            (MapSite)
"""
from __future__ import annotations

from dataclasses import dataclass

import clang.cindex as cc

from ..regex_detect import GrowthSite, MapSite
from .parse import _extra, _infile_funcs, _walk


@dataclass
class ByValSite:
    """A heavy (class/container) parameter passed BY VALUE — a `const&` avoids the
    copy. `start..end` is the char span of the whole param decl to replace."""
    func: str
    start: int
    end: int
    new_text: str
    old_text: str


# --- offset / token / type helpers ---

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


def _is_call_on(call, var: str, method: str) -> bool:
    toks = [t.spelling for t in call.get_tokens()]
    return len(toks) >= 3 and toks[0] == var and toks[1] == "." and toks[2] == method


def _is_op_on(node, var: str, op: str) -> bool:
    toks = [t.spelling for t in node.get_tokens()]
    return len(toks) >= 2 and toks[0] == var and toks[1] == op   # e.g. `s +=`


def _for_bound(for_stmt) -> str | None:
    for c in for_stmt.get_children():
        if c.kind == cc.CursorKind.BINARY_OPERATOR:
            toks = [t.spelling for t in c.get_tokens()]
            if "<" in toks:
                rhs = toks[toks.index("<") + 1:]     # whole RHS, e.g. "data.size()"
                return "".join(rhs) if rhs else None
    return None


def _is_string(t) -> bool:
    s = t.spelling
    return s.startswith("std::string") or "basic_string<char" in s


# --- vector growth ---

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
    return [s for fn in _infile_funcs(source, _extra()) if (s := _growth_in_fn(fn, source))]


def growth_ast(source: str) -> GrowthSite | None:
    sites = all_growth(source)
    return sites[0] if sites else None


def growth_in_ast(source: str, func: str) -> GrowthSite | None:
    return next((s for s in all_growth(source) if s.func == func), None)


# --- string growth ---

def _string_growth_in_fn(fn, source: str) -> GrowthSite | None:
    """A std::string grown by +=/append/push_back inside a loop, with no prior
    reserve() — the string analog of _growth_in_fn (compiler can't pre-size it)."""
    nodes = list(_walk(fn))
    calls = [c for c in nodes if c.kind == cc.CursorKind.CALL_EXPR]
    fors = [c for c in nodes if c.kind == cc.CursorKind.FOR_STMT]
    for v in nodes:
        if v.kind != cc.CursorKind.VAR_DECL or not _is_string(v.type):
            continue
        var = v.spelling
        if any(_is_call_on(c, var, "reserve") for c in calls):
            continue                                            # already reserved
        for fs in fors:
            inner = list(_walk(fs))
            grown = any(_is_call_on(c, var, "append") or _is_call_on(c, var, "push_back")
                        for c in inner if c.kind == cc.CursorKind.CALL_EXPR) \
                or any(_is_op_on(c, var, "+=") for c in inner
                       if c.kind in (cc.CursorKind.CALL_EXPR,
                                     cc.CursorKind.COMPOUND_ASSIGNMENT_OPERATOR))
            if grown:
                return GrowthSite(func=fn.spelling, var=var, bound=_for_bound(fs),
                                  insert_at=_stmt_end(source, v), elem_type="char")
    return None


def all_string_growth(source: str) -> list[GrowthSite]:
    return [s for fn in _infile_funcs(source, _extra()) if (s := _string_growth_in_fn(fn, source))]


def string_growth_in_ast(source: str, func: str) -> GrowthSite | None:
    return next((s for s in all_string_growth(source) if s.func == func), None)


# --- map → unordered_map ---

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
    return [s for fn in _infile_funcs(source, _extra()) if (s := _map_in_fn(fn, source))]


def map_ast(source: str) -> MapSite | None:
    sites = all_map(source)
    return sites[0] if sites else None


def map_in_ast(source: str, func: str) -> MapSite | None:
    return next((s for s in all_map(source) if s.func == func), None)


# --- unordered_map reserve ---

def _umap_growth_in_fn(fn, source: str) -> GrowthSite | None:
    """A std::unordered_map grown by insert/emplace/subscript in a loop, with no
    prior reserve() and a computable bound — reserve(n) removes the rehashing."""
    nodes = list(_walk(fn))
    calls = [c for c in nodes if c.kind == cc.CursorKind.CALL_EXPR]
    fors = [c for c in nodes if c.kind == cc.CursorKind.FOR_STMT]
    for v in nodes:
        if v.kind != cc.CursorKind.VAR_DECL or not v.type.spelling.startswith("std::unordered_map"):
            continue
        var = v.spelling
        if any(_is_call_on(c, var, "reserve") for c in calls):
            continue                                            # already reserved
        for fs in fors:
            inner = list(_walk(fs))
            grown = any(_is_call_on(c, var, "insert") or _is_call_on(c, var, "emplace")
                        for c in inner if c.kind == cc.CursorKind.CALL_EXPR)
            if not grown:                                       # subscript growth: `m[...]`
                toks = [t.spelling for t in fs.get_tokens()]
                grown = any(toks[i] == var and toks[i + 1] == "["
                            for i in range(len(toks) - 1))
            if grown:
                b = _for_bound(fs)
                if b:                                           # need a size to reserve
                    return GrowthSite(func=fn.spelling, var=var, bound=b,
                                      insert_at=_stmt_end(source, v), elem_type="")
    return None


def all_umap_growth(source: str) -> list[GrowthSite]:
    return [s for fn in _infile_funcs(source, _extra()) if (s := _umap_growth_in_fn(fn, source))]


def umap_growth_in_ast(source: str, func: str) -> GrowthSite | None:
    return next((s for s in all_umap_growth(source) if s.func == func), None)


# --- pass heavy parameter by const-reference ---

def _byval_in_fn(fn, source: str):
    """Yield ByValSite for each heavy (class/container) parameter `fn` takes BY
    VALUE — not already a reference/pointer, and not a defaulted arg (which the
    rewrite would drop). Correctness is gate-backstopped: if the body actually
    mutates the param, `const&` won't compile and the gate rejects it."""
    for p in fn.get_arguments():
        t = p.type
        if t.kind in (cc.TypeKind.LVALUEREFERENCE, cc.TypeKind.RVALUEREFERENCE, cc.TypeKind.POINTER):
            continue
        try:
            if t.get_canonical().kind != cc.TypeKind.RECORD:   # class/struct/container (not primitive)
                continue
        except Exception:
            continue
        start = _b2c(source, p.extent.start.offset)
        end = _b2c(source, p.extent.end.offset)
        name_off = _b2c(source, p.location.offset)
        name = p.spelling
        if not name or name_off <= start:
            continue
        old_text = source[start:end]
        if "=" in old_text:                                    # defaulted arg → skip (would drop default)
            continue
        type_text = source[start:name_off].rstrip()
        if not type_text:
            continue
        prefix = "" if type_text.startswith("const") else "const "
        new_text = f"{prefix}{type_text}& {name}"
        if new_text == old_text:
            continue
        yield ByValSite(func=fn.spelling, start=start, end=end,
                        new_text=new_text, old_text=old_text)


def byval_params(source: str) -> list[ByValSite]:
    out: list[ByValSite] = []
    for fn in _infile_funcs(source, _extra()):
        out.extend(_byval_in_fn(fn, source))
    return out


def byval_in_ast(source: str, func: str) -> "ByValSite | None":
    return next((s for s in byval_params(source) if s.func == func), None)
