#include "geo.h"
#include <vector>
#include <cstddef>

// route_costs has a harnessable signature (size_t -> vector<int>) AND a reserve
// opportunity (out grows by push_back with a known bound n). But it also calls
// point_weight(), which lives in geo.cpp — a separate TU. Verifying it REQUIRES
// linking against the rest of the build. This is the Phase-1 item #1 proof:
// self-contained mode skips it; link-against-build verifies + accepts the reserve.
std::vector<int> route_costs(std::size_t n) {
    std::vector<int> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back(point_weight(i) + (int)i);
    return out;
}
