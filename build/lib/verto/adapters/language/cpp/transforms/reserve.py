"""reserve() before a growth loop — vector (the v0 flagship) and string.

Both insert `container.reserve(bound)` before a loop that grows the container with
no prior reserve — leaving ~40–71% on the table that the compiler can't recover
(it can't prove the final size). They share everything but which detector finds the
site (and vector additionally rewrites push_back → emplace_back).
"""
from __future__ import annotations

from .....engine.models import Contract
from ..regex_detect import (detect_all_growth, detect_all_string_growth,
                            detect_all_umap_growth, detect_growth, detect_growth_in,
                            detect_string_growth_in, detect_umap_growth_in)
from .base import Transform


class _ReserveBase(Transform):
    """Insert `s.reserve(bound);` before a growth loop. Subclasses supply `_site`
    (the single site, respecting target_func) and `_all_sites` (every site, for
    candidate discovery), and may extend the rewrite/patch."""

    def _site(self, source: str):
        raise NotImplementedError

    def _all_sites(self, source: str) -> list:
        raise NotImplementedError

    def candidates(self, source: str) -> list[str]:
        return [s.func for s in self._all_sites(source) if s.func and s.bound]

    def matches(self, source: str) -> bool:
        s = self._site(source)
        return s is not None and s.bound is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        s = self._site(source)
        if s is None or not s.bound:
            return None
        new = source[:s.insert_at] + f"\n    {s.var}.reserve({s.bound});" + source[s.insert_at:]
        new = self._extra_rewrite(s, new)
        return new, self._patch(s)

    def _extra_rewrite(self, s, new: str) -> str:
        return new

    def _patch(self, s) -> str:
        return f"@@ {s.func}() @@\n+    {s.var}.reserve({s.bound});\n"


class ReserveBeforePushback(_ReserveBase):
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

    def _all_sites(self, source: str) -> list:
        return detect_all_growth(source)

    def _extra_rewrite(self, s, new: str) -> str:
        return new.replace(f"{s.var}.push_back", f"{s.var}.emplace_back")

    def _patch(self, s) -> str:
        return (f"@@ {s.func}() @@\n"
                f"+    {s.var}.reserve({s.bound});\n"
                f"-    {s.var}.push_back(...)  ->  {s.var}.emplace_back(...)\n")


class ReserveString(_ReserveBase):
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

    def _all_sites(self, source: str) -> list:
        return detect_all_string_growth(source)


class ReserveUnorderedMap(_ReserveBase):
    name = "reserve_unordered_map"
    rationale = "std::unordered_map grown in a loop with no reserve() — rehashes ~log2(n)×"

    def contract(self) -> Contract:
        return Contract(
            precondition=[
                "loop trip count is loop-invariant (computable before the loop)",
                "the map is not aliased or observed elsewhere during the loop",
            ],
            postcondition="output-equivalent",
        )

    def _site(self, source: str):
        if self.target_func:
            return detect_umap_growth_in(source, self.target_func)
        sites = detect_all_umap_growth(source)
        return sites[0] if sites else None

    def _all_sites(self, source: str) -> list:
        return detect_all_umap_growth(source)
