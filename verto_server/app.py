"""verto_server HTTP API — the hosted endpoint the free client's `--model hosted` calls.

Stdlib `http.server` (no new deps — matches VERTO's stdlib-first ethos; production would swap in
FastAPI/uvicorn behind a load balancer). Run:  python -m verto_server.app

  GET  /healthz        → liveness
  POST /v1/optimize    → {source, filename?}  (Authorization: Bearer <verto-token>)
                         → {plan, results:[{function, accepted, p50_delta_pct, diff, ...}]}
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import entitlement
from .managed_model import optimize_hosted


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            return self._json(200, {"ok": True, "service": "verto_server"})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/optimize":
            return self._json(404, {"error": "not found"})

        # 1) THE PAYWALL — verified here, server-side, so the open client can't bypass it (P4).
        ent = entitlement.check(self._token())
        if ent is None:
            return self._json(401, {"error": "invalid or missing verto-token"})
        if not entitlement.has(ent, "hosted-model"):
            return self._json(403, {"error": f"plan {ent.plan!r} does not include the hosted model"})

        # 2) parse the request
        try:
            body = json.loads(self._read_body())
            source = body["source"]
        except (ValueError, KeyError):
            return self._json(400, {"error": "expected JSON body {source, filename?}"})

        # 3) run the CORE engine on our compute — same gate, same proof — and return it
        try:
            results = optimize_hosted(source, body.get("filename", "input.cpp"), ent)
        except Exception as e:                                  # never leak a stack trace to callers
            return self._json(500, {"error": f"{type(e).__name__}"})
        self._json(200, {"plan": ent.plan, "results": results})

    # --- helpers ---
    def _token(self) -> str:
        h = self.headers.get("Authorization", "")
        return h[7:].strip() if h.startswith("Bearer ") else self.headers.get("X-Verto-Token", "")

    def _read_body(self) -> str:
        n = int(self.headers.get("Content-Length", 0) or 0)
        return self.rfile.read(n).decode("utf-8") if n else "{}"

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_a):                                # quiet by default
        pass


def serve(host: str = "127.0.0.1", port: int = 8724) -> None:
    print(f"verto_server (PRIVATE — never publish) → http://{host}:{port}   POST /v1/optimize")
    ThreadingHTTPServer((host, port), _Handler).serve_forever()


if __name__ == "__main__":
    serve()
