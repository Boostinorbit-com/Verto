"""#10 LLM proposer — deterministic mechanism + opt-in live Qwen smoke tests.

The mechanism (span/splice/parse) is tested without a model. The live tests are **opt-in**
(`BOOSTOPT_LIVE_LLM=1`): they load a model that pegs the CPU, which would add benchmark
contention and make the perf-gated tests flaky. Off by default → the suite is deterministic;
run them explicitly to exercise the real model.
"""
import os
import urllib.request

import pytest

_LIVE = bool(os.environ.get("BOOSTOPT_LIVE_LLM"))

from boostopt.adapters.language.cpp.regex_detect import detect_all_functions, detect_func_span
from boostopt.adapters.language.cpp.transforms.verbatim import VerbatimRewrite
from boostopt.adapters.proposer.frontier import FrontierProposer
from boostopt.engine.config import Config
from boostopt.engine.models import Evidence, Target

_SRC = ("#include <vector>\n#include <cstddef>\n"
        "std::vector<long> squares(std::size_t n){ std::vector<long> out;"
        " for(std::size_t i=0;i<n;++i) out.push_back((long)(i*i)); return out; }")


def _cfg():
    c = Config()
    c.model = "local"
    return c


def test_all_functions_and_span():
    assert detect_all_functions(_SRC) == ["squares"]        # LLM candidate pool = any function
    assert detect_func_span(_SRC, "squares") is not None


def test_verbatim_rewrite_splices_over_the_function():
    new_code = ("std::vector<long> squares(std::size_t n){ std::vector<long> out(n);"
                " for(std::size_t i=0;i<n;++i) out[i]=(long)(i*i); return out; }")
    t = VerbatimRewrite("squares", new_code)
    assert t.matches(_SRC)
    new, _ = t.rewrite(_SRC)
    assert "out(n)" in new and "push_back" not in new


def test_verbatim_same_code_is_noop():
    span = detect_func_span(_SRC, "squares")
    same = _SRC[span[0]:span[1]]
    assert VerbatimRewrite("squares", same).rewrite(_SRC) is None   # nothing to try


def test_parse_candidate_extracts_fenced_block():
    p = FrontierProposer(_cfg())
    cand = p._parse_candidate("Here you go:\n```cpp\nvoid f(){}\n```\nDone.", "f")
    assert cand and cand.transform.name == "llm_rewrite"


def test_parse_candidate_empty_reply_is_none():
    assert FrontierProposer(_cfg())._parse_candidate("", "f") is None


def _ollama_up() -> bool:
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False


@pytest.mark.live
@pytest.mark.skipif(not (_LIVE and _ollama_up()),
                    reason="live LLM test — set BOOSTOPT_LIVE_LLM=1 (and run Ollama) to enable")
def test_frontier_v1_transport():
    """The frontier path (local=False → OpenAI-compatible /v1/chat/completions with a Bearer
    key) is the same code a paid key uses. Ollama serves /v1 and ignores the key, so we prove
    the transport — request shape, response parse, token-usage extraction — for free."""
    import socket

    from boostopt.runtime import llm
    try:
        # /v1 doesn't carry Ollama's think:false, so a reasoning model can be slow to first
        # token when cold — this is a transport smoke test, so skip (don't fail) on timeout.
        r = llm.chat("Reply with only the code.", "Write int add(int a,int b) in one line.",
                     base_url="http://127.0.0.1:11434", model="qwen3:0.6b",
                     local=False, api_key="ollama-dummy", timeout=30)
    except (socket.timeout, TimeoutError, OSError) as e:
        pytest.skip(f"Ollama /v1 slow/unavailable: {e}")
    assert r.text.strip()                 # parsed choices[0].message.content
    assert r.in_tokens > 0 and r.out_tokens > 0   # usage extracted (feeds the #12 budget)


def test_frontier_reads_api_key_from_env(monkeypatch):
    """--model frontier resolves the key from the environment, never a flag."""
    from types import SimpleNamespace
    from boostopt.surfaces.cli.config_build import _build_config
    monkeypatch.delenv("BOOSTOPT_LLM_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    args = SimpleNamespace(model="frontier")
    cfg = _build_config(args)
    assert cfg.llm_api_key == "sk-from-env"
    monkeypatch.setenv("BOOSTOPT_LLM_API_KEY", "sk-boostopt-wins")
    assert _build_config(SimpleNamespace(model="frontier")).llm_api_key == "sk-boostopt-wins"


@pytest.mark.live
@pytest.mark.skipif(not (_LIVE and _ollama_up()),
                    reason="live LLM test — set BOOSTOPT_LIVE_LLM=1 (and run Ollama) to enable")
def test_live_qwen_proposes_a_rewrite():
    """Live: the local model responds and we parse a rewrite candidate (or gracefully None —
    we don't assert ACCEPT, since a small model's output varies)."""
    ev = Evidence(target=Target("x.cpp", "squares", 0, "cpp"), source=_SRC)
    cand = FrontierProposer(_cfg()).propose(ev, None)
    assert cand is None or cand.transform.name == "llm_rewrite"


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  PASS {name}")
    print("ok")
