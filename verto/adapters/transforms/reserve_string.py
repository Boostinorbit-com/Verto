"""reserve() before a std::string built with += in a loop.

The string analog of reserve_before_pushback: a std::string grown char-by-char
reallocates ~log2(n) times; `s.reserve(n)` up front removes them (~40% measured).
The compiler cannot do this — it can't prove the final length before the loop.
"""
from __future__ import annotations

from ...engine.models import Contract
from ..language.cpp._detect import detect_all_string_growth, detect_string_growth_in
from .base import Transform


class ReserveString(Transform):
    name = "reserve_string"
    rationale = "std::string grown by += with no prior reserve()"

    def contract(self) -> Contract:
        return Contract(
            precondition=[
                "loop trip count is loop-invariant (computable before the loop)",
                "the string is not aliased or observed elsewhere during the loop",
            ],
            postcondition="output-equivalent",
        )

    def _site(self, source: str):
        if self.target_func:
            return detect_string_growth_in(source, self.target_func)
        sites = detect_all_string_growth(source)
        return sites[0] if sites else None

    def matches(self, source: str) -> bool:
        s = self._site(source)
        return s is not None and s.bound is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        s = self._site(source)
        if s is None or not s.bound:
            return None
        new = source[:s.insert_at] + f"\n    {s.var}.reserve({s.bound});" + source[s.insert_at:]
        patch = f"@@ {s.func}() @@\n+    {s.var}.reserve({s.bound});\n"
        return new, patch
