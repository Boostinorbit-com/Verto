// A project header — the .cpp files below #include it, so libclang CANNOT parse
// them (and `Count` won't resolve) without `-Iinclude`, which comes from
// compile_commands.json. This is what makes codebase mode necessary.
#pragma once
#include <vector>
#include <cstddef>

using Count = int;                                  // project typedef

std::vector<Count> build_histogram(std::size_t n);

struct Bucket { int lo, hi, count; };
std::vector<Bucket> bucketize(const std::vector<Count>& h, int width);
