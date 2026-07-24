#include "stats.h"
#include <cstdio>

// The project's OWN bench: calls scaled with a large n in a hot loop. Its wall time is
// 2A's perf signal — reserve() removes the reallocation churn, dropping the run time.
int main() {
    std::map<int, long> m;
    for (int i = 0; i < 8; ++i) m[i] = i;
    unsigned long acc = 0;
    for (int r = 0; r < 3000; ++r) {
        auto v = scaled(m, 20000);
        acc += v.size() + (unsigned long)v.back();
    }
    std::printf("%lu\n", acc);
    return 0;
}
