"""Real profile reader — rank functions by measured cost (Phase-1 item #5).

`--profile FILE` lets VERTO optimize the functions that are actually HOT in a real
run, instead of guessing with a synthetic micro-benchmark. A real repo has
thousands of functions; the profile says which ones matter.

Supported formats (auto-detected), all mapped to {leaf function name: self-cost}:
  * JSON        — {"foo": 12.3, "ns::Bar::baz(int)": 4.1}
  * perf        — `perf report --stdio` text ("  42.10%  bin  bin  [.] foo")
  * gprof       — flat profile ("  33.3    0.02   0.02   100   ...  foo(unsigned long)")
  * plain       — "foo 12.3" or just "foo" per line (cost defaults to 1.0)

Symbols are reduced to their LEAF identifier (namespaces, template args and
parameter lists stripped) so a profile's `ns::Foo::bar(int)` matches the source
function `bar`. Costs for the same leaf are summed. Best-effort: an unreadable or
unrecognized file yields {} (VERTO falls back to the micro-profiler).
"""
from __future__ import annotations

import functools
import json
import re

_PERF = re.compile(r"^\s*(\d+\.\d+)%.*\[[.k]\]\s+(.+?)\s*$")     # perf report --stdio
_GPROF = re.compile(r"^\s*(\d+\.\d+)\s+[\d.]+\s+[\d.]+\s+.*?\s+(\S.*?)\s*$")
_PLAIN = re.compile(r"^\s*(\S.*?)\s+(\d+(?:\.\d+)?)\s*$")


def _leaf(symbol: str) -> str:
    """`ns::Foo::bar(int)&` → `bar`. Strip parameter list, template args, and the
    namespace/class qualification, leaving the bare function identifier."""
    s = symbol.strip()
    depth = 0                                   # drop the parameter list (balanced parens)
    cut = len(s)
    for i, ch in enumerate(s):
        if ch == "(" and depth == 0:
            cut = i
            break
    s = s[:cut]
    s = re.sub(r"<.*>", "", s)                  # template args
    s = s.split("::")[-1]                       # namespace / class
    m = re.search(r"[A-Za-z_]\w*$", s)          # trailing identifier (drops operators/&/*)
    return m.group(0) if m else s.strip()


def _parse(text: str) -> dict[str, float]:
    text = text.strip()
    if not text:
        return {}
    if text[0] in "{[":                         # JSON
        try:
            obj = json.loads(text)
        except ValueError:
            obj = None
        if isinstance(obj, dict):
            out: dict[str, float] = {}
            for k, v in obj.items():
                try:
                    out[_leaf(str(k))] = out.get(_leaf(str(k)), 0.0) + float(v)
                except (TypeError, ValueError):
                    continue
            return out

    costs: dict[str, float] = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "%", "time", "index", "Flat", "granularity", "Each sample")):
            continue
        m = _PERF.match(line) or _GPROF.match(line)
        if m:
            leaf = _leaf(m.group(2))
            if leaf:
                costs[leaf] = costs.get(leaf, 0.0) + float(m.group(1))
            continue
        m = _PLAIN.match(line)
        if m:
            leaf = _leaf(m.group(1))
            if leaf:
                costs[leaf] = costs.get(leaf, 0.0) + float(m.group(2))
            continue
        # a bare "symbol" line → presence counts as cost 1.0
        tok = line.strip()
        if re.fullmatch(r"[\w:<>~*&(), ]+", tok):
            leaf = _leaf(tok)
            if leaf:
                costs[leaf] = costs.get(leaf, 0.0) + 1.0
    return costs


@functools.lru_cache(maxsize=8)
def load_profile(path: str) -> dict[str, float]:
    """{leaf function name: self-cost} from a profile file; {} if unreadable."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return _parse(f.read())
    except OSError:
        return {}
