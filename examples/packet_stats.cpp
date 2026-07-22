// Example target for VERTO — the canonical reserve() case (VERTO.md §3).
#include <vector>
#include <cstddef>

std::vector<int> build_histogram(std::size_t n) {
    std::vector<int> out;                       // no reserve() → reallocates ~log2(n)×
    for (std::size_t i = 0; i < n; ++i)
        out.push_back(static_cast<int>(i * 2));
    return out;
}
