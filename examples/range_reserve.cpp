#include <vector>
#include <cstddef>

// map_doubled builds a new vector by transforming an input vector in a RANGE-BASED for
// loop `for (x : in)` — the pattern real code uses constantly, and the one VERTO used to
// MISS (it only saw counted `for(i=0;i<n;i++)` loops). The reserve bound is `in.size()`.
// Harnessable: std::vector<int> → std::vector<long>.
std::vector<long> map_doubled(const std::vector<int>& in) {
    std::vector<long> out;
    for (int x : in)
        out.push_back((long)x * 2 + 1);
    return out;
}
