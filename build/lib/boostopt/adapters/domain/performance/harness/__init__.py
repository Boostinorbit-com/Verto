"""Harness generation — assemble a self-contained check|race|bench program for a
function (`template.py`) from synthesized inputs (`synth.py`).

`make_program` is the entry point used by both oracles; `supported` /
`unsupported_reason` are the verify-or-skip predicates.
"""
from .template import generate, generate as make_program, supported, unsupported_reason

__all__ = ["generate", "make_program", "supported", "unsupported_reason"]
