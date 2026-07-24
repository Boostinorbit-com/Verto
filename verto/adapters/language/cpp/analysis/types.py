"""Type analysis over the parsed AST — signatures, clean type spellings, and the
simple-aggregate resolver used by input synthesis (item #2).

Typedefs are resolved so a project's `using Count = int` classifies correctly, and
container/string spellings are normalized (allocator noise stripped) so the
harness's `std::vector<int>` matcher hits.
"""
from __future__ import annotations

import clang.cindex as cc

from .parse import _extra, _infile_funcs, _infile_records, _tu


def _clean_type(ct) -> str:
    """A harness-classifier-friendly spelling: resolve typedefs (so a project
    `using Count = int` → `int`, `std::size_t` → `unsigned long`) and normalize
    containers/strings to their clean form — WITHOUT the allocator noise that raw
    canonicalization adds (which would defeat the classifier's `std::vector<int>`
    match). Peels a reference first so `const std::vector<int>&` is handled."""
    t = ct
    try:
        if t.kind in (cc.TypeKind.LVALUEREFERENCE, cc.TypeKind.RVALUEREFERENCE):
            t = t.get_pointee()
        if "vector" in t.spelling and t.get_num_template_arguments() >= 1:
            el = t.get_template_argument_type(0).get_canonical().spelling
            return f"std::vector<{el}>"
        canon = t.get_canonical().spelling
        if "basic_string<char" in canon:
            return "std::string"
        return canon
    except Exception:
        return ct.spelling


def signature(source: str, func: str) -> tuple[list[str], str] | None:
    """(param type spellings, return type spelling) for `func`, or None.
    Typedefs are resolved so codebase code (project typedefs) classifies correctly."""
    for fn in _infile_funcs(source, _extra()):
        if fn.spelling == func:
            return [_clean_type(a.type) for a in fn.get_arguments()], _clean_type(fn.result_type)
    return None


def aggregate_fields(source: str, typename: str, extra: tuple[str, ...] = ()):
    """Public data-member `(name, clean type)` list for a SIMPLE aggregate
    struct/class `typename`, or None if it isn't one the harness can synthesize:
    a user-declared constructor, a base class, a virtual method, or any non-public
    data member disqualifies it (so brace-initialization `T{v0, v1, …}` is valid).
    Reference/pointer/qualifier noise on `typename` is peeled first (item #2)."""
    name = typename.replace("const", "").replace("&", "").replace("*", "").strip()
    name = name.split("::")[-1]
    if not name:
        return None
    try:
        tu = _tu(source, tuple(extra) or _extra())
    except Exception:
        return None
    for rec in _infile_records(tu):
        if rec.spelling != name:
            continue
        fields = []
        for c in rec.get_children():
            k = c.kind
            if k == cc.CursorKind.CXX_BASE_SPECIFIER:
                return None                                   # base class → not simple
            if k == cc.CursorKind.CONSTRUCTOR:
                return None                                   # any declared ctor → brace-init unsafe
            if k == cc.CursorKind.CXX_METHOD and getattr(c, "is_virtual_method", lambda: False)():
                return None
            if k == cc.CursorKind.FIELD_DECL:
                if c.access_specifier != cc.AccessSpecifier.PUBLIC:
                    return None                               # private/protected member
                fields.append((c.spelling, _clean_type(c.type)))
        return fields or None
    return None
