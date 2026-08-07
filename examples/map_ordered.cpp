// UNSAFE case for map -> unordered_map.
// The output is the distinct keys IN ITERATION ORDER. std::map iterates in
// sorted key order; std::unordered_map does not — so the output ORDER is
// observed and the swap is ILLEGAL. BOOSTOPT's order-sensitive differential test
// sees the changed sequence and REJECTS it — the contract enforced by measurement.
#include <map>
#include <vector>
#include <cstddef>

std::vector<int> distinct_keys(std::size_t n) {
    std::map<int, int> seen;
    for (std::size_t i = 0; i < n; ++i)
        seen[static_cast<int>((i * 2654435761u) % 1000)]++;

    std::vector<int> out;
    out.reserve(seen.size());
    for (const auto& kv : seen)                                  // iterates in KEY ORDER
        out.push_back(kv.first);
    return out;
}
