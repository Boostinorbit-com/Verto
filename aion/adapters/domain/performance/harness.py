"""Test-harness generation for the Performance domain.

Builds a self-contained program = (function-under-test source) + a generated
driver `main()`. Two modes:
  - correctness: read n values from stdin, print an ORDER-SENSITIVE checksum per
    input (FNV-1a over the returned sequence) so that a change which alters
    element ORDER (e.g. map -> unordered_map when iteration order is observed)
    is caught — a commutative sum would miss it.
  - timing: run the function N reps, print per-rep elapsed ms.

v0 assumes the flagship signature `std::vector<int> f(std::size_t)`. Generic
signature handling comes with the libclang sensor (build step 5).
"""
from __future__ import annotations

_PRELUDE = "#include <cstdio>\n#include <cstdlib>\n#include <chrono>\n#include <cstdint>\n"

_CORRECTNESS_MAIN = """
int main() {{
    unsigned long n;
    while (std::scanf("%lu", &n) == 1) {{
        auto v = {func}(n);
        unsigned long long h = 1469598103934665603ULL;               // FNV-1a, ORDER-sensitive
        for (auto x : v) {{ h ^= (unsigned long long)(unsigned int)x; h *= 1099511628211ULL; }}
        std::printf("%zu %llu\\n", (size_t)v.size(), h);
    }}
    return 0;
}}
"""

_TIMING_MAIN = """
int main(int argc, char** argv) {{
    unsigned long n = argc > 1 ? std::strtoul(argv[1], nullptr, 10) : 2000000UL;
    int reps = argc > 2 ? std::atoi(argv[2]) : 30;
    volatile long sink = 0;
    for (int w = 0; w < 3; ++w) {{ auto v = {func}(n); sink += (long)v.size(); }}  // warmup
    for (int r = 0; r < reps; ++r) {{
        auto t0 = std::chrono::steady_clock::now();
        auto v = {func}(n);
        auto t1 = std::chrono::steady_clock::now();
        sink += (long)v.size();
        std::printf("%.6f\\n", std::chrono::duration<double, std::milli>(t1 - t0).count());
    }}
    (void)sink; return 0;
}}
"""


def make_program(source: str, func: str, mode: str) -> str:
    main = _CORRECTNESS_MAIN if mode == "correctness" else _TIMING_MAIN
    return _PRELUDE + source + "\n" + main.format(func=func)
