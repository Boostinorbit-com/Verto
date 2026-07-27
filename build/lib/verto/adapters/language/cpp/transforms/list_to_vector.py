"""std::list -> std::vector — a STRUCTURAL (data-structure) change.

Wedge category A: a compiler will never swap a container type, and a tests-only tool
won't either. A std::list built only at the back and iterated pays a heap allocation per
node and pointer-chases on every traversal; std::vector is contiguous — far cache-friendlier
(measured ~20× on build+iterate). The precondition — *no push_front / splice / middle
insert-erase / iterator-stability reliance* — is checked structurally (the detector refuses
any list-only op) AND backstopped by the gate: if the swap changed behavior it's REJECTED.
"""
from __future__ import annotations

from .....engine.models import Contract
from ..regex_detect import detect_all_list, detect_list, detect_list_in
from .base import Transform


class ListToVector(Transform):
    name = "list_to_vector"
    rationale = ("std::list built by push_back and iterated — std::vector is contiguous "
                 "(cache-friendly), far faster to traverse (legal iff no push_front/splice)")

    def contract(self) -> Contract:
        return Contract(
            precondition=[
                "the list is only grown at the back and iterated — no push_front, splice, "
                "middle insert/erase, list-only reorder (sort/merge/reverse/unique/remove), "
                "or reliance on node/iterator stability across insertions",
            ],
            postcondition="output-equivalent",
        )

    def _site(self, source: str):
        return detect_list_in(source, self.target_func) if self.target_func else detect_list(source)

    def candidates(self, source: str) -> list[str]:
        return [s.func for s in detect_all_list(source) if s.func]

    def matches(self, source: str) -> bool:
        return self._site(source) is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        s = self._site(source)
        if s is None:
            return None
        new = source[:s.type_start] + "std::vector" + source[s.type_end:]
        if "#include <vector>" not in new:                        # ensure the header
            i = new.find("#include")
            eol = new.find("\n", i) + 1 if i != -1 else 0
            new = new[:eol] + "#include <vector>\n" + new[eol:]
        patch = (f"@@ {s.func}() @@\n"
                 f"-    std::list<{s.elem}> {s.var};\n"
                 f"+    std::vector<{s.elem}> {s.var};\n")
        return new, patch
