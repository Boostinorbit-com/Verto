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

// gather takes a `const int* src` + a length `n`. B2-a infers the safe read range
// [0, n) from the `(ptr, len)` convention and SYNTHESIZES a buffer, so the reserve
// opportunity is now verified & accepted (it used to be an honest skip). The `const`
// makes the pointer read-only by type; ASan backstops a mis-inferred length.
std::vector<int> gather(const int* src, std::size_t n) {
    std::vector<int> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back(src[i] * 2);
    return out;
}

// mix takes a NON-const `int* src` + length `n`. B2-a only synthesizes `const T*`
// (read-only BY TYPE); a plain `int*` could be written through, so VERTO can't prove
// it's safe to fabricate contents — it has a reserve opportunity but stays an honest
// SKIP (item #4). B2-b (capture real values from a run) is what unlocks this case.
std::vector<int> mix(int* src, std::size_t n) {
    std::vector<int> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back(src[i] + 1);
    return out;
}
