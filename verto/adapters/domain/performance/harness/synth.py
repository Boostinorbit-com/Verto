"""Input synthesis for the harness — classify a function's parameter/return types
and emit the C++ that builds deterministic inputs + serializes the output.

Handles primitives, `std::vector<primitive>`, `std::string`, and simple aggregate
structs (item #2). `None` from `_classify*` means "can't synthesize" → the harness
skips that function (verify-or-skip).
"""
from __future__ import annotations

import re

from ....language.cpp import analysis as _ast

_INT = {"bool",              # measure-first (2026-07-28 skip census): bool was absent → every
                             # bool-returning candidate was skipped (~9% of skips); it serializes
                             # cleanly as 0/1, so treat it as an integer for synth + checksum.
        "char", "signed char", "unsigned char",   # integer-like; also unlocks map<char,…> returns
        "int", "unsigned int", "unsigned", "long", "unsigned long", "long int",
        "unsigned long int", "long long", "unsigned long long", "short", "unsigned short",
        "size_t", "std::size_t", "int64_t", "std::int64_t", "uint64_t", "std::uint64_t"}
_FLOAT = {"double", "float", "long double"}
_STRING = {"std::string", "std::basic_string<char>", "std::__cxx11::basic_string<char>",
           "std::basic_string<char, std::char_traits<char>, std::allocator<char> >"}


def _norm(t: str) -> str:
    return " ".join(t.replace("const", "").replace("&", "").split())


def _strip_alloc(t: str) -> str:
    """Drop `, std::allocator<…>` args so a canonicalized nested type like
    `std::vector<std::vector<int, std::allocator<int>>>` matches the plain shape."""
    prev = None
    while prev != t:
        prev, t = t, re.sub(r",\s*std::allocator<[^<>]*>", "", t)
    return t


def _classify(t: str):
    n = _strip_alloc(_norm(t))
    if n in _INT:
        return ("int", n)
    if n in _FLOAT:
        return ("float", n)
    if n in _STRING:
        return ("string", "")
    m = re.match(r"^std::vector<\s*(.+?)\s*>$", n)
    if m:
        el = _norm(m.group(1))
        if el in _INT or el in _FLOAT:
            return ("vector", el)
        m2 = re.match(r"^std::vector<\s*(.+?)\s*>$", el)      # measure-first: vector<vector<primitive>>
        if m2:                                                # (2D grids/matrices — top skip type)
            inner = _norm(m2.group(1))
            if inner in _INT or inner in _FLOAT:
                return ("vector2d", inner)
    return None


def _classify_param(t: str, source: str):
    """Classify a PARAMETER type — like _classify, but also resolves a simple
    aggregate struct/class (all public primitive fields) to an ("aggregate", …)
    spec whose values the harness synthesizes field-by-field (item #2). None if
    the type can't be synthesized (pointer, non-aggregate class, aggregate with a
    non-primitive field)."""
    c = _classify(t)
    if c is not None:
        return c
    fields = _ast.aggregate_fields(source, _norm(t))
    if not fields:
        return None
    specs = []
    for fname, ftype in fields:
        fc = _classify(ftype)
        if fc is None or fc[0] not in ("int", "float"):      # v0: primitive fields only
            return None
        specs.append((fname, fc))
    return ("aggregate", _norm(t), specs)


def _classify_ret(ret: str, source: str):
    """Classify a RETURN type for CHECKSUMMING. Superset of `_classify_param` (primitives,
    vector, vector2d, aggregate struct) PLUS `(unordered_)map<primitive, primitive>`. Maps are
    RETURN-only — we serialize one, never synthesize one as an input, so map lives here and not
    in `_classify` (which would wrongly mark a map PARAM as buildable)."""
    c = _classify_param(ret, source)
    if c is not None:
        return c
    m = re.match(r"std::(?:unordered_)?map<\s*(.+?)\s*,\s*(.+?)\s*[,>]", _norm(ret))
    if m:                                                 # ignore trailing hash/equal_to/allocator args
        k, v = _classify(m.group(1)), _classify(m.group(2))
        if k and v and k[0] in ("int", "float") and v[0] in ("int", "float"):
            return ("map", "")
    return None


def _agg_field_expr(cat: str, sub: str, idx: int) -> str:
    """A value expression for one aggregate FIELD. Unsigned/size types scale with N
    (they're usually counts/sizes → keeps the reserve win measurable); signed ints
    stay small (avoid signed-overflow UB that UBSan would rightly reject)."""
    if cat == "float":
        return f"({sub})((double)((N + {idx}) % 1000) * 0.001)"
    if "unsigned" in sub or "size_t" in sub or sub in ("uint64_t", "std::uint64_t"):
        return f"({sub})N"
    return f"({sub})((long)(N % 128) + {idx})"


def _builder(spec, name: str) -> str:
    cat = spec[0]
    if cat == "aggregate":
        _, tyname, fields = spec
        vals = ", ".join(_agg_field_expr(fc[0], fc[1], i) for i, (fn, fc) in enumerate(fields))
        return f"            {tyname} {name}{{ {vals} }};"
    sub = spec[1]
    if cat == "int":
        return f"            {sub} {name} = ({sub})N;"
    if cat == "float":
        return f"            {sub} {name} = ({sub})((double)(N % 1000) * 0.001);"
    if cat == "vector":
        return (f"            std::vector<{sub}> {name}; {name}.reserve(N);\n"
                f"            for (unsigned long j = 0; j < N; ++j) "
                f"{name}.push_back(({sub})((j * 2654435761ull) % 1000));")
    if cat == "vector2d":
        # a DIM x DIM matrix with total ~N elements (measurable, matches the flat case) and
        # BOUNDED (no OOM at N=2e6). A dimension the callee assumes differently → out-of-bounds
        # read → ASan traps orig+variant → honest skip, never a false accept.
        return (f"            unsigned long {name}_d = (unsigned long)std::sqrt((double)N) + 1;\n"
                f"            std::vector<std::vector<{sub}>> {name}({name}_d, std::vector<{sub}>({name}_d));\n"
                f"            for (unsigned long ri = 0; ri < {name}_d; ++ri)\n"
                f"              for (unsigned long ci = 0; ci < {name}_d; ++ci)\n"
                f"                {name}[ri][ci] = ({sub})(((ri * {name}_d + ci) * 2654435761ull) % 1000);")
    return (f"            std::string {name}; {name}.reserve(N);\n"
            f"            for (unsigned long j = 0; j < N; ++j) "
            f"{name}.push_back((char)('a' + (j % 26)));")


def _ptr_builder(elem: str, name: str, length_name: str) -> str:
    """B2-a: synthesize a `const T*` parameter as a length-N buffer whose length is
    the paired integer parameter `length_name`. The call passes `<name>_buf.data()`.
    Same fuzz formula as the vector builder — the buffer's contents feed BOTH the
    original and the variant identically, so the differential test stays sound."""
    return (f"            std::vector<{elem}> {name}_buf((size_t){length_name});\n"
            f"            for (unsigned long j = 0; j < (unsigned long){length_name}; ++j) "
            f"{name}_buf[j] = ({elem})((j * 2654435761ull) % 1000);")


def _serialize(spec) -> str:
    cat = spec[0]
    sub = spec[1] if len(spec) > 1 else ""
    if cat == "int":
        return '            std::printf("%lld\\n", (long long)r);'
    if cat == "float":
        return '            std::printf("%.9g\\n", (double)r);'
    if cat == "aggregate":                    # return an aggregate → print each public primitive field
        _, _tyname, fields = spec
        lines = [(f'std::printf("%.9g\\n", (double)r.{fn});' if fc[0] == "float"
                  else f'std::printf("%lld\\n", (long long)r.{fn});') for fn, fc in fields]
        return "            " + "\n            ".join(lines)
    if cat == "map":
        # ORDER-INDEPENDENT checksum: (unordered_)map iteration order is unspecified and may
        # differ between orig/variant, so SUM per-entry hashes (addition commutes) → the digest
        # is identical regardless of order → sound (no false REJECT from a reordered map).
        return ('            { unsigned long long acc = 0; size_t cnt = 0;\n'
                '              for (auto& kv : r) { unsigned long long h = 1469598103934665603ULL;\n'
                '                h = (h ^ (unsigned long long)(long long)kv.first) * 1099511628211ULL;\n'
                '                h = (h ^ (unsigned long long)(long long)kv.second) * 1099511628211ULL;\n'
                '                acc += h; ++cnt; }\n'
                '              std::printf("%zu %llu\\n", cnt, acc); }')
    if cat == "vector" and sub in _FLOAT:
        # print the actual values (not a hash) so an FP-tolerance compare is possible
        # (item #1b) — and it's more reliable than hashing FP bits anyway.
        return ('            { std::printf("%zu", (size_t)r.size());\n'
                '              for (auto x : r) std::printf(" %.9g", (double)x);\n'
                '              std::printf("\\n"); }')
    if cat == "vector2d":
        return ('            { unsigned long long h = 1469598103934665603ULL; size_t cnt = 0;\n'
                '              for (auto& row : r) for (auto x : row) { h ^= (unsigned long long)(long long)x; h *= 1099511628211ULL; ++cnt; }\n'
                '              std::printf("%zu %llu\\n", cnt, h); }')
    elem = "(long long)x" if cat == "vector" else "(unsigned char)x"
    return ('            { unsigned long long h = 1469598103934665603ULL;\n'
            f'              for (auto x : r) {{ h ^= (unsigned long long)({elem}); h *= 1099511628211ULL; }}\n'
            '              std::printf("%zu %llu\\n", (size_t)r.size(), h); }')


def _consume(spec) -> str:
    cat = spec[0]
    if cat in ("int", "float"):
        return "(long long)r"
    if cat == "aggregate":
        return f"(long long)r.{spec[2][0][0]}"     # first field — a cheap live-use sink
    return "(long long)r.size()"                   # vector / vector2d / string / map
