"""Warm daemon — pay Python + libclang startup ONCE, not per invocation.

Mirrors BOOSTOPT_Surfaces (server mode). `boostopt serve` holds a persistent process
whose module-level caches stay warm across requests: the libclang TU cache
(_ast._tu), the include-path probe (_ast._parse_args), and the sanitizer-toolchain
probe (build.sanitizer_toolchain). `boostopt optimize`/`analyze` then become thin
clients over a per-user Unix socket, falling back to in-process execution when no
daemon is running (so nothing breaks without one).

The daemon changes NOTHING about the guarantee — it runs the exact same
_run_command path in a warm interpreter. Requests are handled sequentially, so
the per-request os.chdir (to resolve the client's relative paths) is safe.

Wire protocol (newline-free framing via half-close):
  request : client sends JSON {argv, cwd} then SHUT_WR; daemon reads to EOF
  response: daemon sends JSON {out, err, code} then closes; client reads to EOF
"""
from __future__ import annotations

import json
import os
import socket
import sys
import tempfile
from pathlib import Path


def _sock_path() -> Path:
    base = Path(tempfile.gettempdir()) / f"boostopt-{os.getuid()}"
    base.mkdir(exist_ok=True)
    return base / "daemon.sock"


def _recv_all(conn: socket.socket) -> bytes:
    chunks = []
    while True:
        b = conn.recv(65536)
        if not b:
            return b"".join(chunks)
        chunks.append(b)


def _prewarm() -> None:
    """Load libclang + probe the sanitizer toolchain now, so the FIRST request
    doesn't pay for it. Best-effort — a failure here just means a cold first call."""
    try:
        import importlib
        importlib.import_module("boostopt.engine.api")     # front-load the engine graph
        from ..adapters.language.cpp.build import sanitizer_toolchain
        from ..adapters.language.cpp.regex_detect import detect_all_growth
        sanitizer_toolchain()
        detect_all_growth("#include <vector>\nvoid f(){std::vector<int> v; v.push_back(1);}")
    except Exception:
        pass


def serve(stop: bool = False) -> int:
    sp = _sock_path()

    if stop:
        if not sp.exists():
            print("boostopt: no daemon running", file=sys.stderr)
            return 1
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                c.connect(str(sp))
                c.sendall(json.dumps({"stop": True}).encode())
                c.shutdown(socket.SHUT_WR)
                _recv_all(c)
            print("boostopt: daemon stopped")
            return 0
        except OSError:
            sp.unlink(missing_ok=True)      # stale socket
            print("boostopt: cleared stale daemon socket")
            return 0

    # refuse to double-start; clear a stale socket left by a crashed daemon
    if sp.exists():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                c.connect(str(sp))
            print(f"boostopt: daemon already running on {sp}", file=sys.stderr)
            return 2
        except OSError:
            sp.unlink(missing_ok=True)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(sp))
    srv.listen(16)
    print(f"boostopt daemon listening on {sp}  (Ctrl-C to stop)")
    _prewarm()
    print("boostopt daemon warm — ready.")

    from . import cli
    try:
        while True:
            conn, _ = srv.accept()
            with conn:
                try:
                    req = json.loads(_recv_all(conn) or b"{}")
                    if req.get("stop"):
                        conn.sendall(json.dumps({"out": "", "err": "", "code": 0}).encode())
                        break
                    out, err, code = cli.handle_argv(req.get("argv", []), req.get("cwd"))
                except Exception as e:                          # never let one request kill the daemon
                    out, err, code = "", f"boostopt: daemon error: {e}\n", 2
                conn.sendall(json.dumps({"out": out, "err": err, "code": code}).encode())
    except KeyboardInterrupt:
        print("\nboostopt daemon stopping.")
    finally:
        srv.close()
        sp.unlink(missing_ok=True)
    return 0


def try_client(argv: list[str]) -> tuple[str, str, int] | None:
    """Send the command to a running daemon; return (out, err, code), or None if
    no daemon is reachable (caller then runs in-process)."""
    sp = _sock_path()
    if not sp.exists():
        return None
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.connect(str(sp))
    except OSError:
        return None
    try:
        with c:
            c.sendall(json.dumps({"argv": list(argv), "cwd": os.getcwd()}).encode())
            c.shutdown(socket.SHUT_WR)
            data = _recv_all(c)
        resp = json.loads(data)
        return resp["out"], resp["err"], resp["code"]
    except (OSError, ValueError, KeyError):
        return None
