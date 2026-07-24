#include <list>
#include <cstddef>

// list_sum builds a std::list by push_back and then iterates it. The list only ever
// grows at the back and is read front-to-back — so std::vector is behavior-equivalent
// and far faster (contiguous storage vs a heap node + pointer-chase per element). The
// compiler can't change the container type, and a tests-only tool won't either.
long list_sum(std::size_t n) {
    std::list<long> xs;
    for (std::size_t i = 0; i < n; ++i)
        xs.push_back((long)(i * 3 + 1));
    long s = 0;
    for (long x : xs) s += x;                 // order-independent sum → deterministic
    return s;
}
