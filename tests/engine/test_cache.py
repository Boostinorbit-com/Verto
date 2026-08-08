"""Best-so-far rewrite cache — reuse a function's best VERIFIED rewrite on a re-run (skip the
slow proposer). A FLOOR, never a ceiling: `--refine` re-runs and keeps the faster; `--apply`
re-verifies before writing; a code or model change misses the cache. Never a correctness risk.
"""
import pytest

import os
import tempfile
from pathlib import Path

from boostopt.engine.api import Engine
from boostopt.engine.cache import RewriteCache
from boostopt.engine.config import Config

_SRC = ("#include <vector>\n#include <cstddef>\n"
        "std::vector<int> f(std::size_t n){ std::vector<int> o; "
        "for(std::size_t i=0;i<n;++i) o.push_back((int)i); return o; }\n")


def _file(d):
    p = os.path.join(d, "f.cpp")
    Path(p).write_text(_SRC)
    return p


def _eng(cache_path, *, cache=True):
    c = Config()
    c.model = "rules"
    c.use_cache = cache
    e = Engine(c)
    e.cache = RewriteCache(cache_path)
    return e


@pytest.mark.toolchain
def test_second_run_is_cached():
    d = tempfile.mkdtemp()
    fp, cp = _file(d), os.path.join(d, "cache.jsonl")
    eng = _eng(cp)
    v1 = eng.analyze(fp)
    assert v1[0].accepted and not v1[0].cached                    # first run: fresh
    v2 = eng.analyze(fp)
    assert v2[0].accepted and v2[0].cached                        # second run: reused
    assert v2[0].performance.vector["p50_delta_pct"] == v1[0].performance.vector["p50_delta_pct"]


@pytest.mark.toolchain
def test_cache_persists_to_disk():
    d = tempfile.mkdtemp()
    fp, cp = _file(d), os.path.join(d, "cache.jsonl")
    _eng(cp).analyze(fp)                                          # engine #1 writes the entry
    v = _eng(cp).analyze(fp)                                      # engine #2 loads it from disk
    assert v[0].cached


@pytest.mark.toolchain
def test_code_change_invalidates():
    d = tempfile.mkdtemp()
    fp, cp = _file(d), os.path.join(d, "cache.jsonl")
    eng = _eng(cp)
    eng.analyze(fp)
    Path(fp).write_text(_SRC.replace("(int)i", "(int)(i + 1)"))  # edit the function body
    assert not eng.analyze(fp)[0].cached                          # key changed → miss → recompute


@pytest.mark.toolchain
def test_model_change_invalidates():
    d = tempfile.mkdtemp()
    fp, cp = _file(d), os.path.join(d, "cache.jsonl")
    _eng(cp).analyze(fp)
    other = _eng(cp)
    other.config.model = "frontier"                              # a different "brain" → key differs
    assert not other.analyze(fp)[0].cached


@pytest.mark.toolchain
def test_no_cache_bypasses():
    d = tempfile.mkdtemp()
    fp, cp = _file(d), os.path.join(d, "cache.jsonl")
    _eng(cp).analyze(fp)
    assert not _eng(cp, cache=False).analyze(fp)[0].cached        # use_cache=False → always fresh


@pytest.mark.toolchain
def test_refine_reruns_not_cached():
    d = tempfile.mkdtemp()
    fp, cp = _file(d), os.path.join(d, "cache.jsonl")
    eng = _eng(cp)
    eng.analyze(fp)                                              # warm the cache
    eng.config.refine = True                                    # --refine: try to beat the high score
    assert not eng.analyze(fp)[0].cached                         # ignored the cache, re-ran the proposer


@pytest.mark.toolchain
def test_apply_reverifies_and_writes():
    d = tempfile.mkdtemp()
    fp, cp = _file(d), os.path.join(d, "cache.jsonl")
    eng = _eng(cp)
    eng.analyze(fp)                                               # warm the cache (dry-run)
    v = eng.optimize(fp, apply=True)                             # cache hit under --apply
    assert v[0].accepted and v[0].applied and v[0].cached        # re-verified, then written
    assert "reserve" in Path(fp).read_text()                     # the change actually landed on disk
