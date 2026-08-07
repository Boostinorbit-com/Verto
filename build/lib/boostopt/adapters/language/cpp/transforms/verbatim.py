"""Verbatim rewrite — the shape an LLM proposal takes (Phase-3 #10).

The model returns a whole rewritten function; this Transform splices it in over the
original function's source span. From the gate's point of view it is just another
`Variant` — compiled, differential-tested, sanitized, and benchmarked exactly like a
hand-coded transform. So an LLM rewrite is UNTRUSTED and safe: a wrong/garbled/slower
rewrite fails to build or fails the gate and is rejected. Constructed by the proposer with
the target function + the model's code (not pattern-matched from source like the others).
"""
from __future__ import annotations

from .....engine.models import Contract
from ..regex_detect import detect_func_span
from .base import Transform


class VerbatimRewrite(Transform):
    name = "llm_rewrite"
    rationale = "LLM-proposed rewrite (verified by the gate)"

    def __init__(self, func: str, new_code: str) -> None:
        self.target_func = func
        self._new = new_code.strip()

    def contract(self) -> Contract:
        return Contract(precondition=["a model rewrite — its legality is proven by the gate"],
                        postcondition="output-equivalent")

    def candidates(self, source: str) -> list[str]:
        return [self.target_func] if self.target_func else []

    def matches(self, source: str) -> bool:
        return bool(self.target_func) and detect_func_span(source, self.target_func) is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        span = detect_func_span(source, self.target_func)
        if span is None or not self._new:
            return None
        start, end = span
        new = source[:start] + self._new + source[end:]
        if new == source:                       # model returned the same code → nothing to try
            return None
        patch = f"@@ {self.target_func}() @@\n- <original function>\n+ <model rewrite ({len(self._new)} chars)>\n"
        return new, patch
