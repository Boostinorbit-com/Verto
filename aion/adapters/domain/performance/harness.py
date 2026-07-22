"""Unified test-harness generation for the Performance domain.

One self-contained program = (function-under-test source) + a driver `main` that
dispatches on argv[1]:
  - "check": read n values from stdin, print an ORDER-SENSITIVE checksum per input
    (FNV-1a) so a change that alters element ORDER (e.g. map -> unordered_map when
    iteration order is observed) is caught — a commutative sum would miss it.
  - "bench [n] [reps]": run reps timed calls, print per-rep ms; and print the peak
    RSS (VmHWM) to stderr as "MEM_KB".

Because ONE binary does both, the gate compiles each variant once and reuses it
for the correctness diff-test AND the benchmark.

v0 assumes the flagship signature `std::vector<int> f(std::size_t)`.
"""
from __future__ import annotations

_PRELUDE = "#include <cstdio>\n#include <cstdlib>\n#include <chrono>\n#include <cstdint>\n"

_MAIN = """
int main(int argc, char** argv) {{
    const char* mode = argc > 1 ? argv[1] : "bench";
    if (mode[0] == 'c') {{                                        // check
        unsigned long n;
        while (std::scanf("%lu", &n) == 1) {{
            auto v = {func}(n);
            unsigned long long h = 1469598103934665603ULL;       // FNV-1a, ORDER-sensitive
            for (auto x : v) {{ h ^= (unsigned long long)(unsigned int)x; h *= 1099511628211ULL; }}
            std::printf("%zu %llu\\n", (size_t)v.size(), h);
        }}
        return 0;
    }}
    unsigned long n = argc > 2 ? std::strtoul(argv[2], nullptr, 10) : 2000000UL;   // bench
    int reps = argc > 3 ? std::atoi(argv[3]) : 12;
    volatile long sink = 0;
    for (int w = 0; w < 3; ++w) {{ auto v = {func}(n); sink += (long)v.size(); }}   // warmup
    for (int r = 0; r < reps; ++r) {{
        auto t0 = std::chrono::steady_clock::now();
        auto v = {func}(n);
        auto t1 = std::chrono::steady_clock::now();
        sink += (long)v.size();
        std::printf("%.6f\\n", std::chrono::duration<double, std::milli>(t1 - t0).count());
    }}
    (void)sink;
    {{ std::FILE* mf = std::fopen("/proc/self/status", "r");     // peak RSS
       if (mf) {{ char ln[128]; long hwm = 0;
         while (std::fgets(ln, sizeof ln, mf)) if (std::sscanf(ln, "VmHWM: %ld kB", &hwm) == 1) break;
         std::fclose(mf); std::fprintf(stderr, "MEM_KB %ld\\n", hwm); }} }}
    return 0;
}}
"""


def make_program(source: str, func: str) -> str:
    return _PRELUDE + source + "\n" + _MAIN.format(func=func)
