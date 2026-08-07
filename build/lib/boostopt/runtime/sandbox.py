"""Sandbox — run untrusted builds/executions in isolation.

Mirrors BOOSTOPT_Architecture §10 + Roadmap Phase-3 #13. Two layers:

  1. rlimits — RLIMIT_CPU + a wall-clock timeout, so a variant that loops / hangs is
     killed and the gate records a REJECT rather than crashing BOOSTOPT.
  2. namespace isolation (`isolate=True`, for RUNNING untrusted binaries) — via
     bubblewrap: NO network (`--unshare-all` drops the net namespace) and a READ-ONLY
     view of the host filesystem. So code an LLM wrote (Phase 3) cannot reach the
     network or damage the machine, even though the trusted gate is about to run it.
  3. a hard MEMORY cap on isolated runs — a delegated cgroup via `systemd-run --user
     --scope -p MemoryMax=…`. RSS-based, so it is **ASan-safe** (RLIMIT_AS would block
     AddressSanitizer's huge shadow mmap; MemoryMax counts resident pages, which ASan's
     shadow mostly doesn't touch). A memory-bomb variant is OOM-killed inside its cgroup,
     sparing the machine.

Verify-or-degrade: without `bwrap`, isolation falls back to rlimits-only; without a working
`systemd --user` session the memory cap is skipped — both honest and surfaced by
`boostopt verify-setup`.
"""
from __future__ import annotations

import os
import resource
import shutil
import subprocess
from dataclasses import dataclass

_BWRAP = shutil.which("bwrap")
_SYSTEMD_RUN = shutil.which("systemd-run")
_DEFAULT_MEM_MB = 2048            # generous: legit harnesses (+ ASan RSS) fit; a bomb is killed
_systemd_ok: bool | None = None   # lazily probed once
_bwrap_ok: bool | None = None     # lazily probed once (present ≠ usable — see isolation_available)

# process-global policy, set once per run from Config (registry) — so `--no-sandbox` /
# `--sandbox-mem` reach the isolation without threading params through every oracle.
_policy = {"enabled": True, "mem_mb": _DEFAULT_MEM_MB}


def set_policy(*, enabled: bool = True, mem_mb: int | None = None) -> None:
    _policy["enabled"] = bool(enabled)
    if mem_mb:
        _policy["mem_mb"] = int(mem_mb)


@dataclass
class RunResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def isolation_available() -> bool:
    """True iff namespace isolation (bubblewrap) is actually **usable** — PROBED once, not just
    present. A present-but-broken bwrap (e.g. a restricted CI runner / container that denies
    net-namespace or loopback setup — `Operation not permitted`) reports False, so the caller
    degrades to rlimits-only instead of every isolated run failing. Reported by verify-setup."""
    global _bwrap_ok
    if _bwrap_ok is None:
        _bwrap_ok = False
        if _BWRAP:
            try:
                # Exercise the exact setup real runs use — `--unshare-all` (net ns + loopback,
                # which is what fails on locked-down runners) AND the same read-only binds, so a
                # dynamically-linked probe binary can actually load. A bare bind set would false-
                # negative on a working host (no /lib → the linker isn't found).
                true = shutil.which("true") or "/bin/true"
                probe = [_BWRAP, "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev",
                         "--unshare-all", "--die-with-parent"]
                for d in ("/lib", "/lib64", "/bin", "/sbin", "/etc"):
                    if os.path.exists(d):
                        probe += ["--ro-bind", d, d]
                r = subprocess.run(probe + [true], capture_output=True, timeout=10)
                _bwrap_ok = r.returncode == 0
            except Exception:
                _bwrap_ok = False
    return _bwrap_ok


def memory_cap_available() -> bool:
    """True iff a real (cgroup) memory cap is usable — probed once, reported by verify-setup."""
    global _systemd_ok
    if _systemd_ok is None:
        _systemd_ok = False
        if _SYSTEMD_RUN:
            try:
                r = subprocess.run([_SYSTEMD_RUN, "--user", "--scope", "--quiet", "--collect",
                                    "-p", "MemoryMax=64M", "--", "true"],
                                   capture_output=True, timeout=15)
                _systemd_ok = r.returncode == 0
            except Exception:
                _systemd_ok = False
    return _systemd_ok


def _limits(cpu_sec: int):
    def _apply() -> None:                            # CPU only; the memory cap is a cgroup (ASan-safe)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec))
    return _apply


def _memcap_prefix(mem_mb: int) -> list[str]:
    """A delegated-cgroup memory cap via systemd-run (RSS-based → ASan-safe). Empty list if
    no working `systemd --user` session (caller then runs without a hard memory cap)."""
    if not memory_cap_available():
        return []
    return [_SYSTEMD_RUN, "--user", "--scope", "--quiet", "--collect",
            "-p", f"MemoryMax={mem_mb}M", "-p", "MemorySwapMax=0", "--"]


def _isolate_prefix(cmd: list[str], cwd: str | None) -> list[str]:
    """A bubblewrap prefix: no network (`--unshare-all`) + a read-only host filesystem,
    with the executable's dir bound read-only and `cwd` bound writable. Empty list if
    bwrap is unavailable (caller then runs rlimits-only)."""
    if not cmd or not isolation_available():          # probe: present-but-broken bwrap → degrade
        return []
    p = [_BWRAP, "--ro-bind", "/usr", "/usr", "--proc", "/proc", "--dev", "/dev",
         "--unshare-all", "--die-with-parent"]
    for d in ("/lib", "/lib64", "/bin", "/sbin", "/etc"):
        if os.path.exists(d):
            p += ["--ro-bind", d, d]
    bound: set[str] = set()
    # bind the directory of every command argument that is an existing absolute path — so
    # the untrusted binary is visible even when wrapped (e.g. `taskset -c 2 <binary> …`).
    for arg in cmd:
        if arg.startswith("/") and os.path.exists(arg):
            d = os.path.dirname(os.path.abspath(arg))
            if d and d not in bound:
                p += ["--ro-bind", d, d]              # read/execute the binary
                bound.add(d)
    if cwd:
        rc = os.path.abspath(cwd)
        if rc not in bound:
            p += ["--bind", rc, rc]                   # writable scratch (harness may write here)
        p += ["--chdir", rc]
    return p


def run(cmd: list[str], *, cwd: str | None = None, timeout_sec: int = 60,
        mem_mb: int | None = None, input_text: str | None = None,
        isolate: bool = False) -> RunResult:
    """Run `cmd` under rlimits (CPU + wall timeout). `isolate=True` additionally sandboxes
    it for RUNNING untrusted binaries: a no-network, read-only-fs bubblewrap namespace + a
    cgroup memory cap (`mem_mb`, default 2 GB). Compilation calls leave `isolate` off (the
    toolchain needs broad fs access)."""
    if isolate and _policy["enabled"]:                # --no-sandbox flips _policy["enabled"] off
        full = _memcap_prefix(mem_mb or _policy["mem_mb"]) + _isolate_prefix(cmd, cwd) + list(cmd)
    else:
        full = list(cmd)
    try:
        proc = subprocess.run(
            full, cwd=cwd, capture_output=True, text=True,
            timeout=timeout_sec, input=input_text,
            preexec_fn=_limits(timeout_sec),
        )
        return RunResult(proc.stdout, proc.stderr, proc.returncode)
    except subprocess.TimeoutExpired:
        return RunResult("", "timeout", returncode=124, timed_out=True)
