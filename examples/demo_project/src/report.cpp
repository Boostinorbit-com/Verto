// A second TU with a growth site (out.push_back in a loop, no reserve) — BUT it
// returns std::vector<Bucket>, a custom project type VERTO's harness generator
// cannot build/checksum. So VERTO detects the site and HONESTLY SKIPS it
// (verify-or-skip) rather than optimize what it can't verify. No false positive.
#include "stats.h"

std::vector<Bucket> bucketize(const std::vector<Count>& h, int width) {
    std::vector<Bucket> out;
    for (std::size_t i = 0; i < h.size(); ++i)
        out.push_back({(int)i, (int)i + width, h[i]});
    return out;
}
