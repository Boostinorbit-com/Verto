"""reserve() before a push_back growth loop — the v0 flagship transform.

The canonical case from AION.md §3: a std::vector grown by push_back with no
prior reserve leaves ~71% on the table that -O3 cannot recover.
"""
from __future__ import annotations

from ...engine.models import Contract
from ..language.cpp._detect import detect_growth, detect_growth_in
from .base import Transform


class ReserveBeforePushback(Transform):
    name = "reserve_before_pushback"
    rationale = "vector grown by push_back with no prior reserve()"

    def contract(self) -> Contract:
        return Contract(
            precondition=[
                "loop trip count is loop-invariant (computable before the loop)",
                "the vector is not aliased or observed elsewhere during the loop",
                "no exception between reserve() and the loop is observed differently",
            ],
            postcondition="output-equivalent",
        )

    def _site(self, source: str):
        return detect_growth_in(source, self.target_func) if self.target_func else detect_growth(source)

    def matches(self, source: str) -> bool:
        s = self._site(source)
        return s is not None and s.bound is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        s = self._site(source)
        if s is None or not s.bound:
            return None
        new = source[:s.insert_at] + f"\n    {s.var}.reserve({s.bound});" + source[s.insert_at:]
        new = new.replace(f"{s.var}.push_back", f"{s.var}.emplace_back")
        patch = (f"@@ {s.func}() @@\n"
                 f"+    {s.var}.reserve({s.bound});\n"
                 f"-    {s.var}.push_back(...)  ->  {s.var}.emplace_back(...)\n")
        return new, patch
