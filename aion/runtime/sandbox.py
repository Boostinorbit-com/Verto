"""Sandbox — run untrusted builds/executions in isolation.

Mirrors AION_Architecture §10. subprocess + rlimits (CPU + wall-clock timeout),
temp workdir, optional stdin. Any variant that times out / OOMs / crashes -> the
gate records a REJECT, never a crash of AION itself.

NOTE: RLIMIT_AS (address-space cap) is OPT-IN and OFF by default, because
AddressSanitizer mmaps a huge shadow region and RLIMIT_AS breaks it. Real memory
capping should use cgroups (TODO); for v0 we rely on RLIMIT_CPU + wall timeout.
TODO(v0): add `unshare`(CLONE_NEWNET) / bubblewrap for fs + network isolation.
"""
from __future__ import annotations

import resource
import subprocess
from dataclasses import dataclass


@dataclass
class RunResult:
    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


def _limits(cpu_sec: int, mem_mb: int | None):
    def _apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec))
        if mem_mb is not None:                       # off by default (ASan-safe)
            b = mem_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (b, b))
    return _apply


def run(cmd: list[str], *, cwd: str | None = None, timeout_sec: int = 60,
        mem_mb: int | None = None, input_text: str | None = None) -> RunResult:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True,
            timeout=timeout_sec, input=input_text,
            preexec_fn=_limits(timeout_sec, mem_mb),
        )
        return RunResult(proc.stdout, proc.stderr, proc.returncode)
    except subprocess.TimeoutExpired:
        return RunResult("", "timeout", returncode=124, timed_out=True)
