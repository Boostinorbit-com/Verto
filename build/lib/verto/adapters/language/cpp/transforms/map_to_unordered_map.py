"""std::map -> std::unordered_map — a STRUCTURAL (data-structure) change.

Wedge category A (WEDGE_TEST §4): Codeflash structurally refuses data-structure
swaps; a compiler can't do it. The precondition — *iteration order is never
observed* — is enforced by the gate: if the program observes map ordering, the
(order-sensitive) differential test sees changed output and REJECTS. If it
doesn't, the swap is accepted with a real speedup. The contract, enforced by
measurement.
"""
from __future__ import annotations

from .....engine.models import Contract
from ..regex_detect import detect_all_map, detect_map, detect_map_in
from .base import Transform


class MapToUnorderedMap(Transform):
    name = "map_to_unordered_map"
    rationale = "std::map used for lookups — unordered_map avoids O(log n) tree overhead (legal iff order not observed)"

    def contract(self) -> Contract:
        return Contract(
            precondition=[
                "iteration order of the map is never observed "
                "(no ordered traversal, lower_bound/upper_bound, or begin()-order reliance)",
            ],
            postcondition="output-equivalent (checked order-sensitively)",
        )

    def _site(self, source: str):
        return detect_map_in(source, self.target_func) if self.target_func else detect_map(source)

    def candidates(self, source: str) -> list[str]:
        return [s.func for s in detect_all_map(source) if s.func]

    def matches(self, source: str) -> bool:
        return self._site(source) is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        s = self._site(source)
        if s is None:
            return None
        new = source[:s.type_start] + "std::unordered_map" + source[s.type_end:]
        if "#include <unordered_map>" not in new:                 # ensure the header
            i = new.find("#include")
            eol = new.find("\n", i) + 1 if i != -1 else 0
            new = new[:eol] + "#include <unordered_map>\n" + new[eol:]
        patch = (f"@@ {s.func}() @@\n"
                 f"-    std::map<{s.key}, {s.val}> {s.var};\n"
                 f"+    std::unordered_map<{s.key}, {s.val}> {s.var};\n")
        return new, patch
