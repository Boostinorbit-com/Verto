// Category D (multi-objective) baseline.
// Expensive per-element work over only 500k distinct inputs → lots of recomputation.
// A memoized variant is CORRECT and FASTER, but keeps a big table resident, so it
// regresses peak memory. AION should ACCEPT it under a lenient memory budget but
// REJECT it under a strict one — "faster" is not the whole story.
#include <vector>
#include <cstddef>

static int heavy(int x) {
    long s = 0;
    for (int k = 1; k <= 64; ++k) s += (long)x * k % (k + 7);
    return (int)(s & 0x7fffffff);
}

std::vector<int> transform_seq(std::size_t n) {
    std::vector<int> out;
    out.reserve(n);
    for (std::size_t i = 0; i < n; ++i)
        out.push_back(heavy((int)(i % 500000)));    // recompute every time
    return out;
}
