"""Pointer+length analysis — Phase-1 item #2, tier B2-a.

Identify `const T*` parameters that are SAFE TO SYNTHESIZE as a buffer, so BOOSTOPT can
harness `f(const T* p, size_t n)` (e.g. `gather`) WITHOUT recording real argument
values (that is B2-b). Soundness rests on three facts:

  * `const T*` is **read-only by type** — the callee cannot write through it, so
    synthesizing arbitrary contents can't corrupt caller state.
  * the length is the sibling integer parameter the pointer is indexed against
    (the ubiquitous `(ptr, len)` C convention).
  * a *mis-inferred* length can only cause an out-of-bounds READ, which ASan traps
    on BOTH the original and the variant → the gate can't get a clean run → it
    SKIPS the function. It can never produce a false accept.
"""
from __future__ import annotations

import clang.cindex as cc

from .parse import _extra, _infile_funcs

_INT = {"int", "unsigned int", "unsigned", "long", "unsigned long", "long long",
        "unsigned long long", "short", "unsigned short", "size_t", "std::size_t",
        "int64_t", "std::int64_t", "uint64_t", "std::uint64_t", "ptrdiff_t"}
_PRIM = _INT | {"double", "float", "char", "unsigned char", "signed char"}


def _norm(t: str) -> str:
    return " ".join(t.replace("const", "").replace("&", "").split())


def _subscripted(fn, pname: str) -> bool:
    """The parameter is used as `pname[...]` — indexed like a buffer, not passed
    around as an opaque handle. A cheap token check (`pname` immediately followed
    by `[`), which is exactly what we want to allow."""
    toks = [t.spelling for t in fn.get_tokens()]
    return any(toks[i] == pname and toks[i + 1] == "[" for i in range(len(toks) - 1))


def pointer_length_pairs(source: str, func: str) -> dict:
    """`{ptr_param_index: (element_type, length_param_index)}` for `const T*`
    parameters (T primitive) that are safe to synthesize as a length-N buffer.
    Empty dict if none — the function then stays an honest skip as before."""
    try:
        fns = _infile_funcs(source, _extra())
    except Exception:
        return {}
    for fn in fns:
        if fn.spelling != func:
            continue
        args = list(fn.get_arguments())
        int_idx = [j for j, a in enumerate(args) if _norm(a.type.spelling) in _INT]
        pairs: dict = {}
        for i, a in enumerate(args):
            t = a.type
            if t.kind != cc.TypeKind.POINTER:
                continue
            pointee = t.get_pointee()
            if not pointee.is_const_qualified():          # read-only BY TYPE only
                continue
            elem = _norm(pointee.spelling)
            if elem not in _PRIM:                         # v0: pointer-to-primitive
                continue
            if not _subscripted(fn, a.spelling):          # must be indexed (a buffer)
                continue
            after = [j for j in int_idx if j > i]         # the (ptr, len) convention
            length = after[0] if after else (int_idx[0] if int_idx else None)
            if length is None:                            # no integer to use as a length
                continue
            pairs[i] = (elem, length)
        return pairs
    return {}
