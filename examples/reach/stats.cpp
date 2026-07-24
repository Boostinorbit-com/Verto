#include <map>
#include <vector>

// scaled takes a std::map parameter — which VERTO CANNOT synth-harness — so without 2A
// it is an honest SKIP. Its body grows a std::vector by push_back in a counted loop with
// NO reserve(), so the `reserve` transform matches. That change is BODY-ONLY (the
// signature is untouched), so it doesn't break the project's separate declarations.
//
// 2A (test-reuse PRIMARY oracle): with --test-command (correctness) + --bench-command
// (perf), VERTO verifies the reserve() change against the project's OWN test + bench —
// reaching a real win the synthetic harness alone cannot.
std::vector<long> scaled(const std::map<int, long>& m, int n) {
    std::vector<long> out;
    long base = (long)m.size();
    for (int i = 0; i < n; ++i)
        out.push_back(base * i);          // grows n times with no reserve → reserve(n)
    return out;
}
