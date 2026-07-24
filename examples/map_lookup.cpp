#include <map>
#include <cstddef>

// count_hits queries a fixed std::map in a hot loop. `if (t.count(q)) … t.at(q)` walks
// the tree TWICE per hit; a single find() walks it once (measured ~31%). This is the
// fusion niche: when a map must stay ordered (so map→unordered_map isn't legal), fusing
// the double lookup is the remaining win — one a compiler can't do. Harnessable (size_t→long).
//
// NOTE: here order isn't actually observed, so VERTO prefers the bigger map→unordered_map
// swap; force fusion with --transforms 'fuse_map_lookup' to see this transform in isolation.
long count_hits(std::size_t n) {
    static const std::map<int, long> t = [] {
        std::map<int, long> m;
        for (int i = 0; i < 2000; ++i) m[i] = (long)i * 3 + 1;
        return m;
    }();
    long s = 0;
    for (std::size_t i = 0; i < n; ++i) {
        int q = (int)(i % 2000);
        if (t.count(q)) s += t.at(q);          // count + at = two tree walks → fuse to find()
    }
    return s;
}
