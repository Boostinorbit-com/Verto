#include "other.h"
// Exercises ONLY unrelated() — never references stats.cpp's symbols, so 2A-1 must NOT
// run this test when optimizing stats.cpp.
int main() { return unrelated(3) == 10 ? 0 : 1; }
