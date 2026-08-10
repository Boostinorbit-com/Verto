#include <vector>
#include <cstddef>

// A deliberately un-optimized function: it builds a vector element-by-element with push_back
// in a loop. The LLM proposer (`--model local`, a local Qwen) rewrites it; BOOSTOPT's gate keeps
// the rewrite ONLY if it's verified correct (identical output, sanitizer-clean) AND faster.
// The model is untrusted — a wrong or slower rewrite is simply rejected.
std::vector<long> squares(std::size_t n) {
    std::vector<long> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back((long)(i * i));
    return out;
}
