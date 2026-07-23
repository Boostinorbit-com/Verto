"""Shared build step for the Performance oracles.

Both oracles build the SAME unified programs at the SAME flags, so when the gate
hands them a VerifyCtx (shared workdir + cache), the original/variant are compiled
once by whichever oracle runs first and reused by the other. Without a ctx (direct
callers), each call builds in its own throwaway cache.
"""
from __future__ import annotations

from ...language.cpp.build import Artifact, compile_pair, compile_program

# default codegen; a shared flag set → cache is shareable. -pthread: the harness
# contains a concurrent "race" mode (std::thread, item #1a), so every build links it.
OPT = ["-std=c++20", "-O2", "-march=native", "-pthread"]


def get_or_build_pair(ctx, wd: str, prog_a: str, name_a: str,
                      prog_b: str, name_b: str) -> tuple[Artifact, Artifact]:
    cache = ctx.cache if ctx is not None else {}
    # base -O2/-march=native, + codebase -I/-D/-std, + the project's REAL codegen
    # flags LAST so its -O/-march override the defaults (item #6). orig+variant use
    # the identical set, so the shared-binary cache still holds.
    flags = (OPT + list(getattr(ctx, "extra_cflags", ()) or [])
             + list(getattr(ctx, "opt_flags", ()) or []))
    link = tuple(getattr(ctx, "link_inputs", ()) or ())          # +codebase project archive
    a, b = cache.get(prog_a), cache.get(prog_b)
    if a is None and b is None:                  # both missing → compile in parallel
        a, b = compile_pair(
            dict(source_code=prog_a, out_path=f"{wd}/{name_a}", flags=flags, workdir=wd, link_inputs=link),
            dict(source_code=prog_b, out_path=f"{wd}/{name_b}", flags=flags, workdir=wd, link_inputs=link))
    elif a is None:
        a = compile_program(prog_a, f"{wd}/{name_a}", flags=flags, workdir=wd, link_inputs=link)
    elif b is None:
        b = compile_program(prog_b, f"{wd}/{name_b}", flags=flags, workdir=wd, link_inputs=link)
    cache[prog_a], cache[prog_b] = a, b
    return a, b
