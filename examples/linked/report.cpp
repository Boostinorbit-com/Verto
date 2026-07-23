#include <vector>
#include <cstddef>

// Config is a simple aggregate (all public primitive fields, no constructor), so
// VERTO can now SYNTHESIZE an input for scaled_series — the reserve opportunity is
// verified & accepted where before it was skipped ("can't build a Config"). This
// is the aggregate-synthesis slice of capture & replay (Phase-1 item #2).
struct Config { std::size_t n; int scale; };

std::vector<int> scaled_series(const Config& cfg) {
    std::vector<int> out;
    for (std::size_t i = 0; i < cfg.n; ++i)
        out.push_back((int)(i % 256) + cfg.scale);      // overflow-safe by construction
    return out;
}

// gather takes a raw pointer — NOT synthesizable (no length/ownership info in the
// type). It still has a reserve opportunity, so it stays an honest SKIP with a
// reason (item #4): capture & replay of real pointer args is future work.
std::vector<int> gather(const int* src, std::size_t n) {
    std::vector<int> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back(src[i] * 2);
    return out;
}
