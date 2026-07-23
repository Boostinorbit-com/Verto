#include "geo.h"

int point_weight(std::size_t i) {
    return (int)((i * 2654435761ULL) % 97);
}
