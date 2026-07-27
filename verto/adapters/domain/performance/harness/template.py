"""The unified check|race|bench harness program + the public "can we harness it?"
predicates.

Reads a function's ACTUAL signature (via libclang), synthesizes inputs (see
`synth.py`), and assembles a self-contained C++ program with three modes:
  check  — run on stdin-fed sizes, emit an order-sensitive checksum (Rung 1)
  race   — call the fn from 4 threads (ThreadSanitizer, item #1a)
  bench  — timed reps + peak-memory (VmHWM)

`generate` returns None (→ VERTO skips the function; it only optimizes what it can
verify) for signatures `synth` can't safely build.
"""
from __future__ import annotations

import re

from ....language.cpp import analysis as _ast
from .synth import _builder, _classify, _classify_param, _consume, _ptr_builder, _serialize

# Real-world .cpp files ship their own `int main()`; the harness appends its OWN driver
# main, so we rename the file's main out of the way (it's dead code in the harness — the
# function under test is called directly). Without this, every real program fails to build
# with "conflicting types for 'main'".
_MAIN_RE = re.compile(r"\bint\s+main\s*\(")


def _neutralize_main(source: str) -> str:
    return _MAIN_RE.sub("int _verto_user_main(", source)

_PRELUDE = ("#include <cstdio>\n#include <cstdlib>\n#include <cstdint>\n"
            "#include <chrono>\n#include <vector>\n#include <string>\n#include <thread>\n")

_TEMPLATE = """<<PRELUDE>>
<<SOURCE>>

int main(int argc, char** argv) {
    const char* mode = argc > 1 ? argv[1] : "bench";
    if (mode[0] == 'c') {                                        // check
        unsigned long N;
        while (std::scanf("%lu", &N) == 1) {
<<BUILD>>
            auto r = <<CALL>>;
<<SERIALIZE>>
        }
        return 0;
    }
    if (mode[0] == 'r') {                                        // race (ThreadSanitizer, item #1a)
        unsigned long N = argc > 2 ? std::strtoul(argv[2], nullptr, 10) : 4096UL;
<<BUILD>>
        const int NT = 4;                                       // call the fn concurrently to
        std::thread th[NT];                                     // surface a race INSIDE the fn
        volatile long long sinks[NT];                          // (shared static state). PER-THREAD
        for (int t = 0; t < NT; ++t) sinks[t] = 0;             // sinks (distinct addresses) so the
        for (int t = 0; t < NT; ++t)                           // harness's own accumulator never
            th[t] = std::thread([&, t]{ auto r = <<CALL>>; sinks[t] += <<CONSUME>>; });   // races —
        for (int t = 0; t < NT; ++t) th[t].join();             // else TSan flags US, not the fn.
        (void)sinks;
        return 0;
    }
    unsigned long N = argc > 2 ? std::strtoul(argv[2], nullptr, 10) : 2000000UL;   // bench
    int reps = argc > 3 ? std::atoi(argv[3]) : 12;
<<BUILD>>
    volatile long long sink = 0;
    for (int w = 0; w < 3; ++w) { auto r = <<CALL>>; sink += <<CONSUME>>; }
    for (int rr = 0; rr < reps; ++rr) {
        auto t0 = std::chrono::steady_clock::now();
        auto r = <<CALL>>;
        auto t1 = std::chrono::steady_clock::now();
        sink += <<CONSUME>>;
        std::printf("%.6f\\n", std::chrono::duration<double, std::milli>(t1 - t0).count());
    }
    (void)sink;
    { std::FILE* mf = std::fopen("/proc/self/status", "r");
      if (mf) { char ln[128]; long hwm = 0;
        while (std::fgets(ln, sizeof ln, mf)) if (std::sscanf(ln, "VmHWM: %ld kB", &hwm) == 1) break;
        std::fclose(mf); std::fprintf(stderr, "MEM_KB %ld\\n", hwm); } }
    return 0;
}
"""


def generate(source: str, func: str) -> str | None:
    sig = _ast.signature(source, func)
    if sig is None:
        return None
    params, ret = sig
    pairs = _ast.pointer_length_pairs(source, func)      # B2-a: {ptr_idx: (elem, len_idx)}
    pcats = [("ptrbuf",) + pairs[i] if i in pairs else _classify_param(p, source)
             for i, p in enumerate(params)]
    rcat = _classify(ret)
    if any(c is None for c in pcats) or rcat is None:
        return None
    rc, rsub = rcat

    names = [f"a{i}" for i in range(len(params))]
    pre, ptr, call_args = [], [], []                     # length params BEFORE the buffers that use them
    for i, spec in enumerate(pcats):
        if spec[0] == "ptrbuf":
            _, elem, len_idx = spec
            ptr.append(_ptr_builder(elem, names[i], names[len_idx]))
            call_args.append(f"{names[i]}_buf.data()")
        else:
            pre.append(_builder(spec, names[i]))
            call_args.append(names[i])
    build = "\n".join(pre + ptr)
    call = _ast.qualified_name(source, func)             # ns::func so a namespaced fn resolves
    return (_TEMPLATE
            .replace("<<PRELUDE>>", _PRELUDE)
            .replace("<<SOURCE>>", _neutralize_main(source))
            .replace("<<BUILD>>", build)
            .replace("<<CALL>>", f"{call}(" + ", ".join(call_args) + ")")
            .replace("<<SERIALIZE>>", _serialize(rc, rsub))
            .replace("<<CONSUME>>", _consume(rc)))


def supported(source: str, func: str) -> bool:
    return generate(source, func) is not None


def unsupported_reason(source: str, func: str) -> str | None:
    """Why `func`'s signature can't be harnessed (→ verify-or-skip), or None if it
    can. Human-readable, for the skip log (Phase-1 item #4)."""
    sig = _ast.signature(source, func)
    if sig is None:
        return "signature not resolvable (custom/templated types?)"
    params, ret = sig
    pairs = _ast.pointer_length_pairs(source, func)       # B2-a: safe const-ptr+length pairs
    for i, p in enumerate(params):
        if i in pairs:                                    # const T* + length → synthesizable as a buffer
            continue
        if _classify_param(p, source) is None:
            return f"parameter {i} type {p!r} can't be synthesized as an input"
    rcat = _classify(ret)
    if rcat is None:
        return f"return type {ret!r} can't be checksummed"
    return None
