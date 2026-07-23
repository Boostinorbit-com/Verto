#include <vector>
#include <cstddef>

// The project's own test: exit 0 iff series() behaves as expected.
// Build+run with:  clang++ -std=c++20 series.cpp series_test.cpp -o _t && ./_t
std::vector<int> series(std::size_t n);

int main() {
    auto v = series(100);
    if (v.size() != 100) return 1;
    long sum = 0;
    for (int x : v) sum += x;               // sum of (3i+1), i in [0,100) = 14950
    return sum == 14950 ? 0 : 1;
}
