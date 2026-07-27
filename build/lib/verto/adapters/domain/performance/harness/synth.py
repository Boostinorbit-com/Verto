"""Input synthesis for the harness — classify a function's parameter/return types
and emit the C++ that builds deterministic inputs + serializes the output.

Handles primitives, `std::vector<primitive>`, `std::string`, and simple aggregate
structs (item #2). `None` from `_classify*` means "can't synthesize" → the harness
skips that function (verify-or-skip).
"""
from __future__ import annotations

import re

from ....language.cpp import analysis as _ast

_INT = {"int", "unsigned int", "unsigned", "long", "unsigned long", "long int",
        "unsigned long int", "long long", "unsigned long long", "short", "unsigned short",
        "size_t", "std::size_t", "int64_t", "std::int64_t", "uint64_t", "std::uint64_t"}
_FLOAT = {"double", "float", "long double"}
_STRING = {"std::string", "std::basic_string<char>", "std::__cxx11::basic_string<char>",
           "std::basic_string<char, std::char_traits<char>, std::allocator<char> >"}


def _norm(t: str) -> str:
    return " ".join(t.replace("const", "").replace("&", "").split())


def _classify(t: str):
    n = _norm(t)
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


def _serialize(cat: str, sub: str = "") -> str:
    if cat == "int":
        return '            std::printf("%lld\\n", (long long)r);'
    if cat == "float":
        return '            std::printf("%.9g\\n", (double)r);'
    if cat == "vector" and sub in _FLOAT:
        # print the actual values (not a hash) so an FP-tolerance compare is possible
        # (item #1b) — and it's more reliable than hashing FP bits anyway.
        return ('            { std::printf("%zu", (size_t)r.size());\n'
                '              for (auto x : r) std::printf(" %.9g", (double)x);\n'
                '              std::printf("\\n"); }')
    elem = "(long long)x" if cat == "vector" else "(unsigned char)x"
    return ('            { unsigned long long h = 1469598103934665603ULL;\n'
            f'              for (auto x : r) {{ h ^= (unsigned long long)({elem}); h *= 1099511628211ULL; }}\n'
            '              std::printf("%zu %llu\\n", (size_t)r.size(), h); }')


def _consume(cat: str) -> str:
    return "(long long)r" if cat in ("int", "float") else "(long long)r.size()"
