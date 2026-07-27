"""Correctness-completeness detectors (Phase-1 items #1c / #1d).

These make the gate refuse — with a reason — functions it can't soundly verify on
stdout alone: un-modeled side effects (a non-const file-scope global, or I/O) and
optimizable function templates (need a concrete instantiation).
"""
from __future__ import annotations

import clang.cindex as cc

from .parse import _extra, _infile_funcs, _tu, _walk

_IO_CALLS = {"printf", "fprintf", "sprintf", "snprintf", "vprintf", "fwrite", "fread",
             "fputs", "fputc", "puts", "putchar", "fopen", "fclose", "fscanf", "scanf",
             "perror", "fflush", "system", "rename", "remove", "getenv", "setenv"}
_IO_STREAMS = ("cout", "cerr", "clog", "cin", "ofstream", "ifstream", "fstream",
               "printf", "fopen")


def side_effect_reason(source: str, func: str) -> str | None:
    """Why `func` has observable behaviour the stdout-only diff-test can't compare —
    so VERTO refuses it rather than claim a false equivalence (Phase-1 item #1c).
    Catches: reads/writes of a non-const FILE-SCOPE global (an un-modeled input or
    effect), and I/O. Function-LOCAL statics are intentionally NOT flagged here
    (that's the race/memory axis, items #1a/D), so this doesn't over-skip."""
    for fn in _infile_funcs(source, _extra()):
        if fn.spelling != func:
            continue
        for n in _walk(fn):
            if n.kind == cc.CursorKind.DECL_REF_EXPR:
                ref = n.referenced
                if ref is not None and ref.kind == cc.CursorKind.VAR_DECL:
                    sp = ref.semantic_parent
                    if (sp is not None
                            and sp.kind in (cc.CursorKind.TRANSLATION_UNIT, cc.CursorKind.NAMESPACE)
                            and not ref.type.is_const_qualified()):
                        return f"touches non-const file-scope global {ref.spelling!r} (un-modeled side effect)"
            if n.kind == cc.CursorKind.CALL_EXPR and n.spelling in _IO_CALLS:
                return f"performs I/O ({n.spelling})"
        toks = {t.spelling for t in fn.get_tokens()}
        for s in _IO_STREAMS:
            if s in toks:
                return f"performs I/O ({s})"
        return None
    return None


def template_candidates(source: str, extra: tuple[str, ...] = ()) -> list[str]:
    """Names of in-file function TEMPLATES that look optimizable (item #1d). They
    can't be harnessed without a concrete instantiation, so they're reported as
    honest skips rather than silently ignored (`_infile_funcs` only yields concrete
    FUNCTION_DECLs, so a template never reaches the normal candidate path)."""
    try:
        tu = _tu(source, tuple(extra) or _extra())
    except Exception:
        return []
    out: list[str] = []

    def walk(node):
        for c in node.get_children():
            lf = c.location.file
            if lf is not None and lf.name != "in.cpp":
                continue
            if c.kind == cc.CursorKind.FUNCTION_TEMPLATE and c.is_definition():
                toks = {t.spelling for t in c.get_tokens()}
                if toks & {"push_back", "emplace_back", "map"} or "+=" in toks:
                    out.append(c.spelling)
            walk(c)
    walk(tu.cursor)
    return out
