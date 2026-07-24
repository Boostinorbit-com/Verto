#include <unordered_map>
#include <cstddef>

// build_index fills an unordered_map keyed by i in a loop with NO reserve(), so it
// rehashes ~log2(n)× as it grows. `m.reserve(n)` up front removes them. The
// compiler can't do this — it can't prove the final element count before the loop.
long build_index(std::size_t n) {
    std::unordered_map<int, long> m;
    for (std::size_t i = 0; i < n; ++i)
        m[(int)i] = (long)(i * 3 + 1);
    long s = 0;
    for (auto& kv : m) s += kv.second;      // sum is order-independent → deterministic
    return s;
}
