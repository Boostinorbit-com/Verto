// examples/linked/report.cpp — a showcase of VERTO's HARNESS REACH.
//   Try:  python3 -m verto.surfaces.cli analyze examples/linked/report.cpp --model rules
//   Every function below is now HARNESS-ABLE (VERTO produces a verified ACCEPT / REJECT),
//   EXCEPT mix(), which stays an honest SKIP with a reason. The `[today: …]`-tagged ones are
//   the reach added on 2026-07-28 — before that they were skipped ("can't build the input" /
//   "can't checksum the return type").
#include <vector>
#include <cstddef>
#include <unordered_map>

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

// [today: bool] A `bool` return used to be an honest skip ("can't checksum bool"). `bool` is now
// a primitive (serialized 0/1), so this is harness-able and the reserve on `v` wins → ACCEPT.
bool any_present(std::size_t n) {
    std::vector<int> v;
    for (std::size_t i = 0; i < n; ++i)
        v.push_back((int)(i % 500));
    return v.size() > 0;
}

// [today: struct return] A struct return is now serialized field-by-field (symmetric to the
// aggregate-INPUT synthesis that scaled_series uses). Reserve on the helper `tmp` wins → ACCEPT.
struct Summary { long total; int count; };
Summary summarize(std::size_t n) {
    Summary s{0, 0};
    std::vector<int> tmp;
    for (std::size_t i = 0; i < n; ++i) { tmp.push_back((int)(i % 100)); s.total += (int)(i % 100); }
    s.count = (int)tmp.size();
    return s;
}

// [today: (unordered_)map return] A map return is serialized with an ORDER-INDEPENDENT
// (commutative) checksum, so the map's unspecified iteration order can't cause a false reject.
// Reserve on `tmp` wins → ACCEPT.
std::unordered_map<int, int> histogram(std::size_t n) {
    std::unordered_map<int, int> h;
    std::vector<int> tmp;
    for (std::size_t i = 0; i < n; ++i) { tmp.push_back((int)i); h[(int)(i % 256)]++; }
    return h;
}

// [today: vector<vector<>> RETURN] A nested-vector return is now checksummable. Reserve on the
// outer vector `m` wins → ACCEPT.
std::vector<std::vector<int>> tabulate(std::size_t n) {
    std::vector<std::vector<int>> m;
    for (std::size_t i = 0; i < n; ++i)
        m.push_back({(int)i, (int)(i * 3)});
    return m;
}

// [today: vector<vector<>> PARAM] Taking a 2D-grid parameter used to be unsynthesizable; VERTO
// now fabricates a bounded DIM×DIM matrix just to build the harness — this function only runs at
// all because the grid can now be synthesized. The reserve on `out` (sized by `n`) is a clean
// win → ACCEPT (kept separate from the grid so the win isn't a marginal, noise-flippy 2D case).
std::vector<int> blend(const std::vector<std::vector<int>>& g, std::size_t n) {
    std::vector<int> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back((int)(i % 97) + (int)g.size());
    return out;
}
