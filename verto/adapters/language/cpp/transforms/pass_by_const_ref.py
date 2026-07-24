"""Pass a heavy parameter by const-reference instead of by value.

A function that takes a `std::vector`/`std::string`/`std::map`/struct **by value**
copies it on every call — a cost the compiler can't remove (it can't change the
signature/ABI, and it can't prove the copy is unobserved across the call). Changing
`T v` → `const T& v` removes the copy with identical behaviour.

Sound by construction of the gate: if the body actually *mutates* the parameter,
`const&` won't compile → the gate rejects it; if it changed observable output, the
differential test rejects it. So even an over-eager detector is safe.
"""
from __future__ import annotations

from .....engine.models import Contract
from ..regex_detect import detect_byval_in, detect_byval_params
from .base import Transform


class PassByConstRef(Transform):
    name = "pass_by_const_ref"
    rationale = "heavy parameter passed by value — a const& avoids the per-call copy"

    def contract(self) -> Contract:
        return Contract(
            precondition=[
                "the parameter is not modified in the function body",
                "the argument is not aliased and re-read after a mutation through it",
            ],
            postcondition="output-equivalent",
        )

    def _site(self, source: str):
        if self.target_func:
            return detect_byval_in(source, self.target_func)
        sites = detect_byval_params(source)
        return sites[0] if sites else None

    def candidates(self, source: str) -> list[str]:
        return [s.func for s in detect_byval_params(source)]

    def matches(self, source: str) -> bool:
        return self._site(source) is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        s = self._site(source)
        if s is None:
            return None
        new = source[:s.start] + s.new_text + source[s.end:]
        patch = (f"@@ {s.func}() @@\n"
                 f"-    {s.old_text}\n"
                 f"+    {s.new_text}\n")
        return new, patch
