#include <map>
#include <vector>

// The project's OWN test: exit 0 iff scaled behaves as expected. This is 2A's correctness
// oracle — it verifies the reserve() change VERTO can't reach with a synthetic harness.
std::vector<long> scaled(const std::map<int, long>& m, int n);

int main() {
    std::map<int, long> m;
    for (int i = 0; i < 5; ++i) m[i] = i;          // size() == 5
    auto v = scaled(m, 100);
    if (v.size() != 100) return 1;
    long sum = 0;
    for (long x : v) sum += x;                       // 5 * sum(0..99) = 5 * 4950 = 24750
    return sum == 24750L ? 0 : 1;
}
