"""LLM proposer (Phase-3 #10) — the Proposer backend for `--model local|frontier`.

Mirrors BOOSTOPT_Architecture §12. UNTRUSTED: the gate re-verifies everything, so the model is
a quality knob, not a correctness dependency — a wrong/slower/garbled rewrite is rejected.
Flow: send the hot function's SOURCE + a compact instruction (NOT a raw AST) → the model
returns a whole rewritten function → wrap it as a `VerbatimRewrite` the gate checks like any
transform. Every call is gated by the #12 budget (`can_spend`) and reconciled (`charge`).

`--model local` talks to a local Ollama (free, private — source never leaves the box);
`--model frontier` talks to an OpenAI-compatible host. Any transport error → propose nothing.
"""
from __future__ import annotations

import re

from ...engine.config import Config
from ...engine.models import Candidate, Evidence, Priors
from ...runtime import llm

_SYSTEM = ("You are an expert C++ performance engineer. Rewrite the given function to run "
           "MEASURABLY FASTER while keeping EXACTLY the same behavior and the same signature. "
           "Apply real optimizations: pre-size or reserve() containers to avoid repeated "
           "reallocation, hoist loop-invariant work, avoid unnecessary copies, and pick a "
           "cheaper algorithm where possible. Do NOT just reformat or rename. Reply with ONLY "
           "the rewritten function inside a single ```cpp code block — no prose, no notes.")

_BLOCK = re.compile(r"```(?:cpp|c\+\+|cxx|c)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)


class FrontierProposer:
    def __init__(self, config: Config, budget: object | None = None) -> None:
        self._config = config
        self._budget = budget                        # #12: trusted cost meter (may be None)

    def propose(self, ev: Evidence, priors: Priors) -> Candidate | None:
        func = ev.target.symbol
        if not func:
            return None
        # #12: stop if the run/hotspot budget is spent (the orchestrator resets the hotspot
        # sub-limit once per function via start_hotspot, so N draws share one hotspot cap).
        if self._budget is not None and not self._budget.can_spend():
            return None
        res = self._call_model(self._render_context(ev))
        if res is None:
            return None
        if self._budget is not None:
            self._budget.charge(res.in_tokens, res.out_tokens)
        return self._parse_candidate(res.text, func)

    def _render_context(self, ev: Evidence) -> str:
        """The hot function's SOURCE (focused; not the whole file, not an AST dump)."""
        from ..language.cpp.regex_detect import detect_func_span
        span = detect_func_span(ev.source, ev.target.symbol)
        return ev.source[span[0]:span[1]] if span else ev.source

    def _call_model(self, prompt: str):
        c = self._config
        # #11: when drawing multiple candidates, raise the temperature so the N rewrites are
        # DIVERSE (a near-zero temperature returns near-identical drafts that dedup collapses).
        temp = 0.7 if int(getattr(c, "candidates", 1) or 1) > 1 else 0.1
        try:
            return llm.chat(_SYSTEM, prompt,
                            base_url=getattr(c, "llm_base_url", "http://127.0.0.1:11434"),
                            model=getattr(c, "llm_model", "qwen2.5-coder:7b"),
                            local=(c.model == "local"),
                            api_key=getattr(c, "llm_api_key", None),
                            temperature=temp,
                            timeout=float(getattr(c, "llm_timeout_sec", 180)))
        except Exception:                            # ollama down / timeout / bad reply → no proposal
            return None

    def _parse_candidate(self, reply: str, func: str) -> Candidate | None:
        m = _BLOCK.search(reply)
        code = (m.group(1) if m else reply).strip()  # accept a bare reply if no fenced block
        if not code:
            return None
        from ..language.cpp.transforms.verbatim import VerbatimRewrite
        t = VerbatimRewrite(func, code)
        return Candidate(transform=t, contract=t.contract(), rationale=f"LLM rewrite ({self._config.llm_model})")
