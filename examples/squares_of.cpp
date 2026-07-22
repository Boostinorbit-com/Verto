// A DIFFERENT signature: takes a vector, returns a vector (not f(size_t)).
// The reserve() opportunity is here; VERTO now reads the real signature via
// libclang and generates a harness for it — building a std::vector<int> input
// and checksumming the std::vector<long> output.
#include <vector>
#include <cstddef>

std::vector<long> squares_of(const std::vector<int>& data) {
    std::vector<long> out;
    for (std::size_t i = 0; i < data.size(); ++i)
        out.push_back((long)data[i] * data[i]);
    return out;
}
