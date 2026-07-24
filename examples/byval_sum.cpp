#include <vector>
#include <cstddef>

// sum_all takes the vector BY VALUE — it copies all n elements on every call, yet
// only reads them. Passing `const std::vector<int>&` removes the copy with
// identical output. The compiler can't do this: it can't change the signature.
long sum_all(std::vector<int> v) {
    long s = 0;
    for (int x : v) s += x;
    return s;
}
