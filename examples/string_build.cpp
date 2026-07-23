// A std::string grown by += in a loop with no prior reserve() — reallocates
// ~log2(n) times. reserve(n) up front removes them (~40% here). The compiler
// CANNOT do this: it can't prove the final length before the loop. This is the
// string analog of the vector reserve() case.
#include <string>
#include <cstddef>

std::string build_label(std::size_t n) {
    std::string s;
    for (std::size_t i = 0; i < n; ++i)
        s += static_cast<char>('a' + (i % 26));
    return s;
}
