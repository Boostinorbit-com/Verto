#include <vector>
#include <cstddef>

// A function VERTO can harness (size_t -> vector<int>) with a reserve opportunity.
// The point of this example is item #3: the project ships its OWN test
// (series_test.cpp), so `--test-command` can re-confirm the reserve change against
// the project's real acceptance criteria, not just VERTO's synthetic inputs.
std::vector<int> series(std::size_t n) {
    std::vector<int> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back((int)(i * 3 + 1));
    return out;
}
