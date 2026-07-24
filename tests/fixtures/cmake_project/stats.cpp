#include <map>
#include <vector>

// scaled takes a std::map parameter — unharnessable by the synth harness — and grows a
// vector by push_back in a counted loop with no reserve (a body-only reserve opportunity).
// 2A verifies the reserve() change against THIS project's own ctest suite + bench.
std::vector<long> scaled(const std::map<int, long>& m, int n) {
    std::vector<long> out;
    long base = (long)m.size();
    for (int i = 0; i < n; ++i)
        out.push_back(base * i);
    return out;
}
