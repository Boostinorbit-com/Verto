"""Map-lookup fusion — `if (m.count(k)) … m.at(k) …` → one find() (2B-2).

A `count(k)` then `at(k)`/`m[k]` hashes/searches the key TWICE; a single `find(k)` +
iterator does it once (measured ~31% on lookup-dominated code). The compiler can't fuse
two separate member calls across a branch. Rewrites to:

    auto __vf_it = m.find(k);
    if (__vf_it != m.end()) … __vf_it->second …

Matched narrowly (see the detector) for soundness; the gate backstops any mis-rewrite.
"""
from __future__ import annotations

from .....engine.models import Contract
from ..regex_detect import detect_all_fuse, detect_fuse, detect_fuse_in
from .base import Transform


class FuseMapLookup(Transform):
    name = "fuse_map_lookup"
    rationale = "if(m.count(k)) … m.at(k) does two lookups — one find() does the job"

    def contract(self) -> Contract:
        return Contract(
            precondition=[
                "the map is not mutated between the count() and the at()/[] on the same key",
            ],
            postcondition="output-equivalent",
        )

    def _site(self, source: str):
        return detect_fuse_in(source, self.target_func) if self.target_func else detect_fuse(source)

    def candidates(self, source: str) -> list[str]:
        return [s.func for s in detect_all_fuse(source) if s.func]

    def matches(self, source: str) -> bool:
        return self._site(source) is not None

    def rewrite(self, source: str) -> tuple[str, str] | None:
        s = self._site(source)
        if s is None:
            return None
        edits = [(a, b, "__vf_it->second") for (a, b) in s.accesses]
        edits.append((s.cond_start, s.cond_end, f"__vf_it != {s.var}.end()"))
        edits.append((s.if_start, s.if_start,
                      f"auto __vf_it = {s.var}.find({s.key});\n{s.indent}"))
        new = source
        for a, b, txt in sorted(edits, key=lambda e: e[0], reverse=True):   # right-to-left
            new = new[:a] + txt + new[b:]
        patch = (f"@@ {s.func}() @@\n"
                 f"-    if ({s.var}.count({s.key})) … {s.var}.at({s.key})\n"
                 f"+    auto it = {s.var}.find({s.key}); if (it != {s.var}.end()) … it->second\n")
        return new, patch
