"""verto_server HTTP API — the hosted endpoint the free client's `--model hosted` calls.

Stdlib `http.server` (no new deps — matches VERTO's stdlib-first ethos; production would swap in
FastAPI/uvicorn behind a load balancer). Run:  python -m verto_server.app

  GET  /healthz        → liveness
  POST /v1/optimize    → {source, filename?}  (Authorization: Bearer <verto-token>)
                         → {plan, results:[{function, accepted, p50_delta_pct, diff, ...}]}
"""
from __future__ import annotations

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import entitlement
from .managed_model import optimize_hosted


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/healthz":
            return self._json(200, {"ok": True, "service": "verto_server"})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        self._t0 = time.monotonic()                            # marks a request we log (not /healthz)
        self._log("→", f"{self.command} {self.path}  (received, working…)")
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
            results, final = optimize_hosted(
                source, body.get("filename", "input.cpp"), ent,
                apply=bool(body.get("apply", False)),
                options=body.get("options") if isinstance(body.get("options"), dict) else None)
        except Exception as e:                                  # never leak a stack trace to callers
            return self._json(500, {"error": f"{type(e).__name__}"})
        resp = {"plan": ent.plan, "engine": entitlement.engine_label(ent), "results": results}
        if final is not None:                                  # apply: the fully-optimized file
            resp["applied_source"] = final
        self._json(200, resp)

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
        if getattr(self, "_t0", None) is not None:             # log the response (skips /healthz)
            self._log_out(code, obj)

    # --- terminal logging: show each request hit + its response ---
    def _log(self, arrow: str, msg: str) -> None:
        print(f"[{time.strftime('%H:%M:%S')}] {arrow} {self.client_address[0]:<15} {msg}", flush=True)

    def _log_out(self, code: int, obj) -> None:
        ms = (time.monotonic() - self._t0) * 1000
        if isinstance(obj, dict) and "results" in obj:
            acc = sum(1 for r in obj["results"] if r.get("accepted"))
            detail = (f"plan={obj.get('plan')} engine={obj.get('engine')!r} "
                      f"results={len(obj['results'])} accepted={acc}")
        elif isinstance(obj, dict) and "error" in obj:
            detail = f"error: {obj['error']}"
        else:
            detail = ""
        self._log("←", f"{self.command} {self.path}  {code}  {detail}  ({ms:.0f}ms)")

    def log_message(self, *_a):                                # silence the stdlib default; we log our own
        pass


def _free_port(port: int) -> bool:
    """Kill whatever holds `port` — a dev convenience so a restart TAKES OVER the same port instead
    of failing. (Fine for dev; a real deploy runs one instance behind a supervisor.)"""
    import shutil
    import subprocess
    if shutil.which("fuser"):
        subprocess.run(["fuser", "-k", f"{port}/tcp"], capture_output=True)
        return True
    if shutil.which("ss"):                                       # fallback: find the pid, kill it
        out = subprocess.run(["ss", "-ltnp"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if f":{port} " in line and "pid=" in line:
                pid = line.split("pid=", 1)[1].split(",", 1)[0]
                subprocess.run(["kill", pid], capture_output=True)
                return True
    return False


def serve(host: str | None = None, port: int | None = None) -> None:
    try:                                                        # line-buffer stdout so logs appear
        sys.stdout.reconfigure(line_buffering=True)             # immediately, even redirected to a file
    except Exception:
        pass
    host = host or os.environ.get("VERTO_SERVER_HOST", "127.0.0.1")
    port = int(port or os.environ.get("VERTO_SERVER_PORT", 8724))
    srv = None
    for attempt in (1, 2):
        try:
            srv = ThreadingHTTPServer((host, port), _Handler)
            break
        except OSError as e:
            if attempt == 1:                                     # busy → take over the SAME port
                print(f"verto_server: port {port} busy — freeing it and taking over (dev)…",
                      flush=True)
                _free_port(port)
                time.sleep(1)
                continue
            print(f"verto_server: still can't bind {host}:{port} ({e}). "
                  f"Free it manually:  fuser -k {port}/tcp", file=sys.stderr)
            raise SystemExit(1)
    print("verto_server (PRIVATE — never publish)")
    print(f"  listening on   {host}:{port}   →   http://{host}:{port}")
    print(f"  endpoints      GET /healthz   ·   POST /v1/optimize")
    print("  ── request log (→ received, ← responded) ──────────────────────", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    # `python -m verto_server.app` | `... 8725` (port) | `... 0.0.0.0 8725` (host port)
    _a = sys.argv[1:]
    serve(*(_a if len(_a) == 2 else ([None, _a[0]] if len(_a) == 1 else [])))
