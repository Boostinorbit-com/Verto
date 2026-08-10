"""Thin client for `--model hosted` (PREMIUM).

Sends the file + token to `boostopt_server` and turns the returned JSON into the SAME `Verdict`
objects the local path produces, so the renderer is identical. Holds **zero premium logic** — it
is a dumb caller (the value, the model, and the entitlement check all live server-side). This is
the free client's only link to the paid service. See Docs/BOOSTOPT_Premium.md and boostopt_server/.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

from ..engine.models import (Candidate, Contract, CorrectnessVerdict, PerfVerdict, Verdict,
                             Witness)


class _HostedTransform:
    """A stand-in transform so the existing renderer can show the hosted result unchanged."""
    def __init__(self, func: str) -> None:
        self.name = "hosted"
        self.target_func = func


def run(path: str, *, url: str, token: str, apply: bool = False, backup: bool = False,
        options: dict | None = None, timeout: int = 300) -> list[Verdict]:
    """POST the file to `{url}/v1/optimize` with the token; return verdicts. When `apply=True`, the
    server returns the fully-optimized file and we WRITE it locally (writing `<path>.bak` first if
    `backup`). `options` carries SAFE preferences (the server only tightens the check, never weakens
    it). Raises ValueError with a plain, user-facing message on any failure."""
    if not token:
        raise ValueError("--model hosted needs a token — pass --boostopt-token or set BOOSTOPT_TOKEN. "
                         "(The free tiers use --model rules or --model local instead.)")
    src = Path(path).read_text(encoding="utf-8")
    body = json.dumps({"source": src, "filename": Path(path).name, "apply": apply,
                       "options": options or {}}).encode("utf-8")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/v1/optimize", data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = _detail(e)
        msg = {401: f"hosted: token rejected ({detail}) — check --boostopt-token / BOOSTOPT_TOKEN.",
               403: f"hosted: your plan doesn't include this ({detail}).",
               429: f"hosted: usage limit reached ({detail})."}.get(
                   e.code, f"hosted: server error {e.code} ({detail}).")
        raise ValueError(msg)
    except urllib.error.URLError as e:
        raise ValueError(f"hosted: can't reach the server at {url} ({e.reason}). "
                         f"Is boostopt_server running?  (dev: python -m boostopt_server.app)")
    # honest label straight from the server (it knows the plan + the actual engine that ran).
    label = f"hosted · plan '{payload.get('plan', '?')}' · engine: {payload.get('engine', '?')}"
    verdicts = [_to_verdict(r, label) for r in payload.get("results", [])]
    # apply: the server returns the fully-optimized file — write it, mark the wins applied.
    final = payload.get("applied_source")
    if apply and final is not None:
        p = Path(path)
        if backup:
            Path(f"{path}.bak").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
        p.write_text(final, encoding="utf-8")
        for v in verdicts:
            if v.accepted:
                v.applied = True
    return verdicts


def _detail(e: urllib.error.HTTPError) -> str:
    try:
        return json.loads(e.read().decode("utf-8")).get("error", str(e.code))
    except Exception:
        return str(e.code)


def _to_verdict(r: dict, label: str = "hosted") -> Verdict:
    tx = _HostedTransform(r.get("function") or "?")
    accepted = bool(r.get("accepted"))
    v = Verdict(
        accepted=accepted,
        candidate=Candidate(transform=tx, contract=Contract(), rationale=label),
        correctness=CorrectnessVerdict(rung=int(r.get("rung") or 0), passed=accepted, witness=Witness()),
        performance=PerfVerdict(vector={"p50": float(r.get("p50_ms", 0.0)),
                                        "p50_delta_pct": float(r.get("p50_delta_pct", 0.0))},
                                pareto_pass=accepted, samples=0),
        reason=r.get("reason", "hosted"))
    v.diff = v.udiff = r.get("diff", "")     # server sends one diff; use it for both display + export
    return v
