"""Harness entry point.

`make_program(source, func)` builds the unified check|bench program for a
function by reading its real signature (see harness_gen.py). Returns None when
the signature isn't safely harness-able — VERTO only verifies what it can build.
"""
from __future__ import annotations

from .harness_gen import generate as make_program  # noqa: F401
