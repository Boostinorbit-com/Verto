"""Sample C++ for `boostopt demo`, embedded as source rather than shipped as package data.

Same reason as boostopt/runtime/models/: a compiled (Nuitka `--module`) build has no filesystem
package, so `importlib.resources` cannot find data files — a verified failure, not a theory. A
module constant compiles into the binary and works identically in a pure-Python wheel.

Keep this to one small, self-contained file. It is a demo, not a test corpus; the real fixtures
live in `examples/` and `tests/` and stay out of the distribution entirely.
"""

DEMO_NAME = "packet_stats.cpp"

DEMO_SOURCE = r"""// Example target for BOOSTOPT — the canonical reserve() case (BOOSTOPT.md §3).
#include <vector>
#include <cstddef>

std::vector<int> build_histogram(std::size_t n) {
    std::vector<int> out;                       // no reserve() → reallocates ~log2(n)×
    for (std::size_t i = 0; i < n; ++i)
        out.push_back(static_cast<int>(i * 2));
    return out;
}
"""
