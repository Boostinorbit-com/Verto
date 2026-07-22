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
            "#include <chrono>\n#include <vector>\n#include <string>\n")

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


def _builder(cat: str, sub: str, name: str) -> str:
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


def _serialize(cat: str) -> str:
    if cat == "int":
        return '            std::printf("%lld\\n", (long long)r);'
    if cat == "float":
        return '            std::printf("%.9g\\n", (double)r);'
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
    pcats = [_classify(p) for p in params]
    rcat = _classify(ret)
    if any(c is None for c in pcats) or rcat is None:
        return None
    rc, rsub = rcat
    if rc == "vector" and rsub in _FLOAT:            # FP-vector hashing is unreliable → skip
        return None

    names = [f"a{i}" for i in range(len(params))]
    build = "\n".join(_builder(cat, sub, names[i]) for i, (cat, sub) in enumerate(pcats))
    return (_TEMPLATE
            .replace("<<PRELUDE>>", _PRELUDE)
            .replace("<<SOURCE>>", source)
            .replace("<<BUILD>>", build)
            .replace("<<CALL>>", f"{func}(" + ", ".join(names) + ")")
            .replace("<<SERIALIZE>>", _serialize(rc))
            .replace("<<CONSUME>>", _consume(rc)))


def supported(source: str, func: str) -> bool:
    return generate(source, func) is not None
