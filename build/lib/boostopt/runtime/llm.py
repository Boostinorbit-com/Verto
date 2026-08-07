"""Minimal LLM client (Phase-3 #10) — stdlib only, local-first.

Two transports behind one `chat()`:
  - **local** (Ollama): POST `/api/chat` with `think:false` — disables qwen3's reasoning so
    a small model answers in seconds with just the code. Free, private (source never leaves
    the box). The default for `--model local`.
  - **frontier** (OpenAI-compatible): POST `/v1/chat/completions` with a Bearer key — for a
    hosted model later. Same parse shape.

UNTRUSTED: whatever it returns is re-verified by the gate, so a bad/slow/garbled reply is a
rejected proposal, never a wrong accept. Any transport error → the caller proposes nothing.
No third-party deps (urllib), so `--model local` needs only a running Ollama.
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass


@dataclass
class LLMResult:
    text: str
    in_tokens: int = 0
    out_tokens: int = 0


@dataclass
class OllamaStatus:
    reachable: bool          # the Ollama daemon answered
    has_model: bool          # the named model is already pulled


def ollama_status(base_url: str, model: str, *, timeout: float = 2.0) -> OllamaStatus:
    """Probe a local Ollama for `boostopt init`: is it up, and is `model` pulled? Never raises —
    a down daemon or any error is reported as (reachable=False, has_model=False)."""
    base = base_url.rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        return OllamaStatus(False, False)
    names = {m.get("name", "") for m in data.get("models", [])}
    has = model in names or f"{model}:latest" in names
    return OllamaStatus(True, has)


def _post(url: str, body: dict, api_key: str | None, timeout: float) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def chat(system: str, user: str, *, base_url: str, model: str, local: bool = True,
         api_key: str | None = None, temperature: float = 0.1,
         timeout: float = 180.0) -> LLMResult:
    """One chat round-trip. Returns the reply text + token counts (for the #12 budget)."""
    base = base_url.rstrip("/")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if local:                                              # Ollama native — think:false = fast
        d = _post(f"{base}/api/chat",
                  {"model": model, "stream": False, "think": False,
                   "options": {"temperature": temperature}, "messages": messages},
                  api_key, timeout)
        return LLMResult(d["message"]["content"],
                         int(d.get("prompt_eval_count", 0)), int(d.get("eval_count", 0)))
    # OpenAI-compatible
    d = _post(f"{base}/v1/chat/completions",
              {"model": model, "temperature": temperature, "messages": messages},
              api_key, timeout)
    u = d.get("usage", {})
    return LLMResult(d["choices"][0]["message"]["content"],
                     int(u.get("prompt_tokens", 0)), int(u.get("completion_tokens", 0)))
