// Category B (profile-guided selection).
// Multiple reserve candidates. cold_path barely runs (8 iterations); hot_path runs n
// times. A static-report tool might optimize the FIRST match (cold_path) — a
// pointless change. VERTO times each candidate and optimizes hot_path — the real
// hotspot — where reserve() is a genuine win.
#include <vector>
#include <cstddef>

std::vector<int> cold_path(std::size_t n) {    // defined FIRST, but negligible
    (void)n;
    std::vector<int> out;
    for (std::size_t i = 0; i < 8; ++i)
        out.push_back((int)i);
    return out;
}

std::vector<int> hot_path(std::size_t n) {     // the real hotspot
    std::vector<int> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back((int)(i * 3));
    return out;
}
