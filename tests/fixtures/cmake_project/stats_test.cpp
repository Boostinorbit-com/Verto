#include "stats.h"
#include <cstdio>

// The project's OWN correctness test (exit 0 = pass).
int main() {
    std::map<int, long> m;
    for (int i = 0; i < 5; ++i) m[i] = i;           // size() == 5
    auto v = scaled(m, 100);
    if (v.size() != 100) return 1;
    long sum = 0;
    for (long x : v) sum += x;                        // 5 * sum(0..99) = 24750
    return sum == 24750L ? 0 : 1;
}
