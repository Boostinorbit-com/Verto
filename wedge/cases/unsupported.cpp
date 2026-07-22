// Harness control: a growth opportunity, but a custom-type param/return and a
// pointer out-param — VERTO cannot safely build inputs / capture output for this
// signature, so it must SKIP it (verify-or-skip; never optimize what it can't check).
#include <vector>

struct Widget { int a, b, c; };

std::vector<Widget> make_widgets(const Widget& seed, int* out_count) {
    std::vector<Widget> v;
    for (int i = 0; i < seed.a; ++i)
        v.push_back({i, i * 2, i * 3});
    if (out_count) *out_count = (int)v.size();
    return v;
}
