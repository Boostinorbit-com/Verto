"""Sandbox namespace isolation (Phase-3 #13) — untrusted binaries get NO network and a
read-only host filesystem via bubblewrap. Skips where bwrap / a compiler isn't available."""
import os
import shutil
import subprocess

import pytest

from boostopt.runtime import sandbox

pytestmark = pytest.mark.skipif(
    not sandbox.isolation_available() or not (shutil.which("clang++") or shutil.which("g++")),
    reason="needs bwrap + a C++ compiler")

_NET = r"""
#include <cstdio>
#include <sys/socket.h>
#include <arpa/inet.h>
int main() {
    int s = socket(AF_INET, SOCK_STREAM, 0);
    sockaddr_in a{}; a.sin_family = AF_INET; a.sin_port = htons(53);
    inet_pton(AF_INET, "8.8.8.8", &a.sin_addr);
    int r = connect(s, (sockaddr*)&a, sizeof a);
    printf("%s\n", r == 0 ? "REACHED" : "blocked");
    return 0;
}
"""

_BENIGN = '#include <cstdio>\nint main(){ printf("hello\\n"); return 0; }'
_MEMBOMB = ('#include <cstdio>\n#include <vector>\nint main(){ std::vector<std::vector<char>> k;'
            ' for(int i=0;i<200;i++) k.emplace_back(64*1024*1024,(char)i);'
            ' printf("REACHED\\n"); return 0; }')
def _build(tmp: str, src: str, name: str) -> str:
    cxx = shutil.which("clang++") or shutil.which("g++")
    cpp = os.path.join(tmp, name + ".cpp")
    with open(cpp, "w") as fh:
        fh.write(src)
    exe = os.path.join(tmp, name)
    subprocess.run([cxx, cpp, "-o", exe], check=True, capture_output=True)
    return exe


def test_isolation_blocks_network(tmp_path):
    exe = _build(str(tmp_path), _NET, "net")
    r = sandbox.run([exe], isolate=True)
    assert r.returncode == 0
    assert "blocked" in r.stdout and "REACHED" not in r.stdout


def test_isolation_runs_benign(tmp_path):
    exe = _build(str(tmp_path), _BENIGN, "ben")
    r = sandbox.run([exe], isolate=True)
    assert r.ok and "hello" in r.stdout


def test_memory_cap_kills_a_bomb(tmp_path):
    """A variant that tries to consume ~12 GB is OOM-killed inside its cgroup, sparing the
    host — the machine never hands it the memory."""
    if not sandbox.memory_cap_available():
        import pytest as _pt
        _pt.skip("no working systemd --user session for a cgroup memory cap")
    exe = _build(str(tmp_path), _MEMBOMB, "bomb")
    r = sandbox.run([exe], isolate=True, mem_mb=512)
    assert "REACHED" not in r.stdout        # never allocated its way to 12 GB
    assert not r.ok                          # killed (non-zero / signalled)


# checks a HARDCODED host path — NOT an argument, since path args are deliberately bound
# into the sandbox (needed for the `taskset <binary>` case); an arg would defeat the test.
_SEE_HOME = ('#include <cstdio>\n#include <unistd.h>\n'
             'int main(){ printf("%s\\n", access("/home", F_OK) == 0 ? "SEES" : "hidden"); return 0; }')


@pytest.mark.skipif(not os.path.exists("/home"), reason="/home not present on host")
def test_isolation_hides_host_fs(tmp_path):
    """The host filesystem outside the bound dirs is invisible in the sandbox."""
    exe = _build(str(tmp_path), _SEE_HOME, "see")
    assert "hidden" in sandbox.run([exe], isolate=True).stdout      # /home not bound → gone


@pytest.mark.skipif(not os.path.exists("/home"), reason="/home not present on host")
def test_no_sandbox_policy_disables_isolation(tmp_path):
    """`--no-sandbox` (set_policy(enabled=False)) drops isolation: a host path the sandbox
    hides becomes visible again. Network-independent."""
    exe = _build(str(tmp_path), _SEE_HOME, "see")
    iso = sandbox.run([exe], isolate=True)               # policy on (default)
    try:
        sandbox.set_policy(enabled=False)
        off = sandbox.run([exe], isolate=True)           # isolate requested, policy disabled
    finally:
        sandbox.set_policy(enabled=True)                 # restore — don't leak to other tests
    assert "hidden" in iso.stdout                        # isolation hides /home
    assert "SEES" in off.stdout                          # --no-sandbox reveals it


if __name__ == "__main__":
    import tempfile
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(tempfile.mkdtemp()); print(f"  PASS {name}")
    print("ok")
