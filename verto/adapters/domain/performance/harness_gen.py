"""Signature-driven harness generation.

Reads a function's ACTUAL signature (via libclang) and generates a unified
check|bench program for it — deterministic, seeded inputs at a scale N, and an
order-sensitive checksum of the return value. Generalises beyond the flagship
`f(std::size_t) -> std::vector<int>` to a broad class of numeric/container
functions.

Returns None (→ VERTO skips the function; it only optimizes what it can verify)
for signatures it can't safely harness: pointers, non-const-ref outputs, custom
types, char, void returns, callbacks, floating-point vector returns, etc.

This is one layer of the harness problem. The robust general answer is capture &
replay of real arguments from the profiling run, and reuse of the project's own
tests — future work (VERTO_Architecture §11).
"""
from __future__ import annotations

import re

from ...language.cpp import _ast

_INT = {"int", "unsigned int", "unsigned", "long", "unsigned long", "long int",
        "unsigned long int", "long long", "unsigned long long", "short", "unsigned short",
        "size_t", "std::size_t", "int64_t", "std::int64_t", "uint64_t", "std::uint64_t"}
_FLOAT = {"double", "float", "long double"}
_STRING = {"std::string", "std::basic_string<char>", "std::__cxx11::basic_string<char>",
           "std::basic_string<char, std::char_traits<char>, std::allocator<char> >"}

_PRELUDE = ("#include <cstdio>\n#include <cstdlib>\n#include <cstdint>\n"
            "#include <chrono>\n#include <vector>\n#include <string>\n#include <thread>\n")

_TEMPLATE = """<<PRELUDE>>
<<SOURCE>>

int main(int argc, char** argv) {
    const char* mode = argc > 1 ? argv[1] : "bench";
    if (mode[0] == 'c') {                                        // check
        unsigned long N;
        while (std::scanf("%lu", &N) == 1) {
<<BUILD>>
            auto r = <<CALL>>;
<<SERIALIZE>>
        }
        return 0;
    }
    if (mode[0] == 'r') {                                        // race (ThreadSanitizer, item #1a)
        unsigned long N = argc > 2 ? std::strtoul(argv[2], nullptr, 10) : 4096UL;
<<BUILD>>
        const int NT = 4;                                       // call the fn concurrently:
        std::thread th[NT];                                     // a transform that added shared
        volatile long long sink = 0;                           // mutable state now races here
        for (int t = 0; t < NT; ++t) th[t] = std::thread([&]{ auto r = <<CALL>>; sink += <<CONSUME>>; });
        for (int t = 0; t < NT; ++t) th[t].join();
        (void)sink;
        return 0;
    }
    unsigned long N = argc > 2 ? std::strtoul(argv[2], nullptr, 10) : 2000000UL;   // bench
    int reps = argc > 3 ? std::atoi(argv[3]) : 12;
<<BUILD>>
    volatile long long sink = 0;
    for (int w = 0; w < 3; ++w) { auto r = <<CALL>>; sink += <<CONSUME>>; }
    for (int rr = 0; rr < reps; ++rr) {
        auto t0 = std::chrono::steady_clock::now();
        auto r = <<CALL>>;
        auto t1 = std::chrono::steady_clock::now();
        sink += <<CONSUME>>;
        std::printf("%.6f\\n", std::chrono::duration<double, std::milli>(t1 - t0).count());
    }
    (void)sink;
    { std::FILE* mf = std::fopen("/proc/self/status", "r");
      if (mf) { char ln[128]; long hwm = 0;
        while (std::fgets(ln, sizeof ln, mf)) if (std::sscanf(ln, "VmHWM: %ld kB", &hwm) == 1) break;
        std::fclose(mf); std::fprintf(stderr, "MEM_KB %ld\\n", hwm); } }
    return 0;
}
"""


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


def generate(source: str, func: str) -> str | None:
    sig = _ast.signature(source, func)
    if sig is None:
        return None
    params, ret = sig
    pcats = [_classify_param(p, source) for p in params]
    rcat = _classify(ret)
    if any(c is None for c in pcats) or rcat is None:
        return None
    rc, rsub = rcat

    names = [f"a{i}" for i in range(len(params))]
    build = "\n".join(_builder(spec, names[i]) for i, spec in enumerate(pcats))
    return (_TEMPLATE
            .replace("<<PRELUDE>>", _PRELUDE)
            .replace("<<SOURCE>>", source)
            .replace("<<BUILD>>", build)
            .replace("<<CALL>>", f"{func}(" + ", ".join(names) + ")")
            .replace("<<SERIALIZE>>", _serialize(rc, rsub))
            .replace("<<CONSUME>>", _consume(rc)))


def supported(source: str, func: str) -> bool:
    return generate(source, func) is not None


def unsupported_reason(source: str, func: str) -> str | None:
    """Why `func`'s signature can't be harnessed (→ verify-or-skip), or None if it
    can. Human-readable, for the skip log (Phase-1 item #4)."""
    sig = _ast.signature(source, func)
    if sig is None:
        return "signature not resolvable (custom/templated types?)"
    params, ret = sig
    for i, p in enumerate(params):
        if _classify_param(p, source) is None:
            return f"parameter {i} type {p!r} can't be synthesized as an input"
    rcat = _classify(ret)
    if rcat is None:
        return f"return type {ret!r} can't be checksummed"
    return None
