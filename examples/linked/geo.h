#pragma once
#include <cstddef>

// Defined in geo.cpp — a DIFFERENT translation unit. A harness for a function
// that calls this used to fail to link (undefined symbol) and get skipped;
// with link-against-the-build (Phase-1 item #1) the archive resolves it.
int point_weight(std::size_t i);
