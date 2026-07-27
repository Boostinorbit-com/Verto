"""Output comparison for the differential test (Rung 1) — exact by default, or
numeric-within-tolerance when `fp_tolerance` is set (item #1b)."""
from __future__ import annotations


def _outputs_match(a: str, b: str, tol: float) -> bool:
    """Exact when tol<=0; otherwise token-wise, with numeric tokens compared within
    relative tolerance `tol` and everything else required equal (item #1b)."""
    if tol <= 0:
        return a == b
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb):
        return False
    for x, y in zip(ta, tb):
        if x == y:
            continue
        try:
            fx, fy = float(x), float(y)
        except ValueError:
            return False
        scale = max(abs(fx), abs(fy), 1e-12)
        if abs(fx - fy) / scale > tol:
            return False
    return True


def _first_diff(a: str, b: str) -> str:
    for i, (x, y) in enumerate(zip(a.splitlines(), b.splitlines())):
        if x != y:
            return f"line {i + 1}: {x!r} != {y!r}"
    return "outputs differ in length"
