"""Light-real detection of optimization sites (shared by Sensor + Mutator).

v0 HEURISTICS via regex — good enough for the flagship cases; the libclang AST
version (VERTO_Architecture §16.1, build step 5) replaces these with something
robust to macros, templates, and multiple candidates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class GrowthSite:
    func: str | None
    var: str
    bound: str | None
    insert_at: int
    elem_type: str


@dataclass
class MapSite:
    func: str | None
    var: str
    key: str
    val: str
    type_start: int      # offset of "std::map" in the declaration
    type_end: int


@dataclass
class ListSite:
    func: str | None
    var: str
    elem: str
    type_start: int      # offset of "std::list" in the declaration
    type_end: int


@dataclass
class FuseSite:
    """A `if (m.count(k)) … m.at(k) …` double-lookup that fuses to one find()."""
    func: str | None
    var: str
    key: str
    if_start: int                    # char offset of `if` — insert the find() before it
    cond_start: int                  # condition span to replace with `__it != var.end()`
    cond_end: int
    accesses: list                   # (start, end) char spans of var.at(key)/var[key] in the then-branch
    indent: str = ""                 # leading whitespace for the inserted find() line


_VEC = re.compile(r"std::vector<\s*([^>]*?)\s*>\s+(\w+)\s*;")
_FUNC = re.compile(r"([A-Za-z_]\w*)\s*\([^;{)]*\)\s*\{")
_BOUND = re.compile(r"for\s*\([^;]*;\s*\w+\s*<\s*([A-Za-z_]\w*)")
_MAP = re.compile(r"std::map<\s*([^,]+?)\s*,\s*([^>]+?)\s*>\s+(\w+)\s*;")


def _enclosing_func(head: str) -> str | None:
    func = None
    for fm in _FUNC.finditer(head):     # nearest function signature before the site
        func = fm.group(1)
    return func


def _growth_regex(source: str) -> GrowthSite | None:
    m = _VEC.search(source)
    if not m:
        return None
    elem_type, var = m.group(1), m.group(2)
    if f"{var}.reserve" in source:                       # already reserved
        return None
    if not re.search(rf"\b{var}\.(push_back|emplace_back)\s*\(", source):
        return None
    bm = _BOUND.search(source[m.end():])
    return GrowthSite(func=_enclosing_func(source[:m.start()]), var=var,
                      bound=bm.group(1) if bm else None, insert_at=m.end(),
                      elem_type=elem_type)


def _map_regex(source: str) -> MapSite | None:
    m = _MAP.search(source)
    if not m:
        return None
    key, val, var = m.group(1).strip(), m.group(2).strip(), m.group(3)
    return MapSite(func=_enclosing_func(source[:m.start()]), var=var, key=key, val=val,
                   type_start=m.start(), type_end=m.start() + len("std::map"))


# --- public API: prefer the robust AST detector, fall back to regex ---

def _ast_only(ast_name: str, *args, default):
    """Call the libclang detector `analysis.<ast_name>(*args)`, returning `default`
    when libclang is unavailable or errors. For the detectors with NO regex fallback
    (string-growth, parse errors, side-effects, templates — items #1c/#1d/#4)."""
    try:
        from . import analysis
        return getattr(analysis, ast_name)(*args)
    except Exception:
        return default


def set_parse_flags(flags) -> None:
    """Tell the libclang parser which compile_commands.json flags to use for the
    next translation unit (include paths, defines, -std). No-op without libclang."""
    try:
        from .analysis import set_parse_args
        set_parse_args(tuple(flags or ()))
    except Exception:
        pass


def detect_growth(source: str) -> GrowthSite | None:
    try:
        from .analysis import growth_ast
        r = growth_ast(source)
        if r is not None:
            return r
    except Exception:
        pass
    return _growth_regex(source)


def detect_map(source: str) -> MapSite | None:
    try:
        from .analysis import map_ast
        r = map_ast(source)
        if r is not None:
            return r
    except Exception:
        pass
    return _map_regex(source)


# --- all-sites / function-scoped (for profile-guided selection across candidates) ---

def detect_all_growth(source: str) -> list[GrowthSite]:
    try:
        from .analysis import all_growth
        r = all_growth(source)
        if r:
            return r
    except Exception:
        pass
    g = _growth_regex(source)
    return [g] if g else []


def detect_growth_in(source: str, func: str | None) -> GrowthSite | None:
    try:
        from .analysis import growth_in_ast
        r = growth_in_ast(source, func) if func else None
        if r is not None:
            return r
    except Exception:
        pass
    g = _growth_regex(source)
    return g if (g and (func is None or g.func == func)) else None


def detect_all_map(source: str) -> list[MapSite]:
    try:
        from .analysis import all_map
        r = all_map(source)
        if r:
            return r
    except Exception:
        pass
    m = _map_regex(source)
    return [m] if m else []


def detect_all_string_growth(source: str) -> list[GrowthSite]:
    return _ast_only("all_string_growth", source, default=[])


def detect_string_growth_in(source: str, func: str | None) -> GrowthSite | None:
    return _ast_only("string_growth_in_ast", source, func, default=None) if func else None


def detect_parse_errors(source: str) -> list[str]:
    """Error-severity libclang diagnostics for the current TU (item #4 skip log)."""
    return _ast_only("parse_errors", source, default=[])


def detect_side_effect_reason(source: str, func: str) -> str | None:
    """Why `func` has un-modeled side effects (item #1c), or None."""
    return _ast_only("side_effect_reason", source, func, default=None)


def detect_template_candidates(source: str) -> list[str]:
    """In-file optimizable function templates to skip-with-reason (item #1d)."""
    return _ast_only("template_candidates", source, default=[])


def detect_all_umap_growth(source: str):
    """std::unordered_map grown in a loop with no reserve() (AST-only)."""
    return _ast_only("all_umap_growth", source, default=[])


def detect_umap_growth_in(source: str, func: str):
    return _ast_only("umap_growth_in_ast", source, func, default=None)


def detect_byval_params(source: str):
    """Heavy parameters passed by value that could be `const&` (AST-only)."""
    return _ast_only("byval_params", source, default=[])


def detect_byval_in(source: str, func: str):
    return _ast_only("byval_in_ast", source, func, default=None)


def detect_map_in(source: str, func: str | None) -> MapSite | None:
    try:
        from .analysis import map_in_ast
        r = map_in_ast(source, func) if func else None
        if r is not None:
            return r
    except Exception:
        pass
    m = _map_regex(source)
    return m if (m and (func is None or m.func == func)) else None


# --- list → vector (AST-only: the no-push_front/splice precondition needs the AST) ---

def detect_all_list(source: str) -> list:
    return _ast_only("all_list", source, default=[])


def detect_list(source: str):
    return _ast_only("list_ast", source, default=None)


def detect_list_in(source: str, func: str | None):
    return _ast_only("list_in_ast", source, func, default=None) if func else None


# --- map-lookup fusion: if(m.count(k)) … m.at(k) → one find() (AST-only) ---

def detect_all_fuse(source: str) -> list:
    return _ast_only("all_fuse", source, default=[])


def detect_fuse(source: str):
    return _ast_only("fuse_ast", source, default=None)


def detect_fuse_in(source: str, func: str | None):
    return _ast_only("fuse_in_ast", source, func, default=None) if func else None


def detect_func_span(source: str, func: str):
    """(start,end) of `func`'s definition — for the LLM verbatim rewrite (#10). AST-only."""
    return _ast_only("func_span", source, func, default=None)


def detect_all_functions(source: str) -> list:
    """Every in-file function name — the LLM proposer's candidate pool (#10). AST-only."""
    return _ast_only("all_functions", source, default=[])
