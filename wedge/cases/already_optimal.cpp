// CONTROL — already optimal: unordered_map (not map) + a reserved vector.
// There is no legal speedup here, so VERTO must find NOTHING. A tool that
// "optimizes" this anyway is producing false positives.
#include <unordered_map>
#include <vector>
#include <cstddef>

std::vector<int> query_freq(std::size_t n) {
    std::unordered_map<int, int> freq;
    for (std::size_t i = 0; i < n; ++i)
        freq[static_cast<int>((i * 2654435761u) % 1000)]++;

    std::vector<int> out;
    out.reserve(1000);
    for (int q = 0; q < 1000; ++q)
        out.push_back(freq.count(q) ? freq[q] : 0);
    return out;
}
