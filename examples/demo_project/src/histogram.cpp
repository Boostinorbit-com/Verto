// A real TU: it #includes a project header, and its return type is the project
// typedef `Count`. VERTO can only resolve that (and thus verify) when parsed with
// the project's `-Iinclude` from compile_commands.json. build_histogram grows a
// vector by push_back with no reserve() → a verifiable optimization.
#include "stats.h"

std::vector<Count> build_histogram(std::size_t n) {
    std::vector<Count> out;
    for (std::size_t i = 0; i < n; ++i)
        out.push_back((Count)(i * 2));
    return out;
}
