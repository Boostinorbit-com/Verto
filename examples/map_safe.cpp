// SAFE case for map -> unordered_map.
// The map is used only for lookups; keys are queried in a FIXED order (0..999),
// so the map's iteration order is never observed. The swap is legal → VERTO
// should ACCEPT it (and it's faster: hash lookups instead of a tree).
#include <map>
#include <vector>
#include <cstddef>

std::vector<int> query_freq(std::size_t n) {
    std::map<int, int> freq;
    for (std::size_t i = 0; i < n; ++i)
        freq[static_cast<int>((i * 2654435761u) % 1000)]++;      // build

    std::vector<int> out;
    out.reserve(1000);
    for (int q = 0; q < 1000; ++q)                               // fixed query order
        out.push_back(freq.count(q) ? freq[q] : 0);
    return out;
}
