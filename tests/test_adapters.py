import json
from types import SimpleNamespace

import duckdb
import pytest

from agent.adapters.base import ChatResult, ToolCall, Usage
from agent.adapters.cache import JsonCache
from agent.adapters.fake import FakeAdapter
from agent.adapters.gateway import Budget, BudgetExceeded, Gateway, estimate_input_tokens
from agent.adapters.ollama import OllamaAdapter
from agent.adapters.pricing import UnknownModelPrice, cost_usd
from agent.adapters.usage import UsageLog

MESSAGES = [{"role": "user", "content": "hi"}]


def _result(text: str = "hello", tin: int = 10, tout: int = 5) -> ChatResult:
    return ChatResult(content=text, tool_calls=[], usage=Usage(tin, tout), model="fake")


@pytest.fixture
def parts(tmp_path):
    return UsageLog(tmp_path / "usage.duckdb"), JsonCache(tmp_path / "cache")


def _usage_rows(usage: UsageLog):
    con = duckdb.connect(str(usage.path), read_only=True)
    return con.execute(
        "SELECT model, prompt_version, input_tokens, output_tokens, cost_usd, cache_hit, run_id "
        "FROM usage ORDER BY ts"
    ).fetchall()


def test_fake_adapter_replays_script_then_fails():
    fake = FakeAdapter([_result("a")])
    assert fake.chat(MESSAGES, []).content == "a"
    assert fake.calls == [(MESSAGES, [])]
    with pytest.raises(RuntimeError, match="script exhausted"):
        fake.chat(MESSAGES, [])


def test_fake_adapter_accepts_callables():
    fake = FakeAdapter([lambda messages: _result(messages[-1]["content"].upper())])
    assert fake.chat(MESSAGES, []).content == "HI"


def test_gateway_logs_usage_and_caches(parts):
    usage, cache = parts
    fake = FakeAdapter([_result()])
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t1")

    first = gw.chat(MESSAGES, [], prompt_version="system.v1")
    second = gw.chat(MESSAGES, [], prompt_version="system.v1")  # same input -> cache

    assert first == second
    assert len(fake.calls) == 1
    assert gw.cache_hits == 1
    assert _usage_rows(usage) == [
        ("fake", "system.v1", 10, 5, 0.0, False, "t1"),
        ("fake", "system.v1", 0, 0, 0.0, True, "t1"),
    ]


def test_cache_key_includes_prompt_version_and_adapter_config(parts):
    usage, cache = parts
    fake = FakeAdapter([_result("v1"), _result("v2")])
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t")
    assert gw.chat(MESSAGES, [], prompt_version="system.v1").content == "v1"
    assert gw.chat(MESSAGES, [], prompt_version="system.v2").content == "v2"

    # review #11: same model name, different settings (e.g. temperature) must not share cache
    other = FakeAdapter([_result("hot")], settings={"temperature": 0.8})
    gw2 = Gateway(other, usage=usage, cache=cache, run_id="t")
    assert gw2.chat(MESSAGES, [], prompt_version="system.v1").content == "hot"


def test_no_cache_always_calls_the_model(parts):
    usage, cache = parts
    fake = FakeAdapter([_result("a"), _result("b")])
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t", use_cache=False)
    gw.chat(MESSAGES, [], prompt_version="p")
    assert gw.chat(MESSAGES, [], prompt_version="p").content == "b"


def test_budget_refuses_a_call_whose_worst_case_exceeds_the_cap(parts, monkeypatch):
    usage, cache = parts
    monkeypatch.setattr("agent.adapters.gateway.cost_usd", lambda model, u: 0.6)
    fake = FakeAdapter([_result("a"), _result("b")])
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t", budget=Budget(cap_usd=1.0))
    gw.chat([{"role": "user", "content": "1"}], [], prompt_version="p")  # 0 + 0.6 <= 1.0
    with pytest.raises(BudgetExceeded, match=r"spent \$0.60.*cap \$1.00"):
        gw.chat([{"role": "user", "content": "2"}], [], prompt_version="p")  # 0.6 + 0.6 > 1.0
    assert len(fake.calls) == 1


def test_unpriced_model_is_refused_before_any_call(parts):
    """Review #5: an unpriced model used to run, log nothing, and never touch the budget."""
    usage, cache = parts
    fake = FakeAdapter([_result()], model="paid-unpriced")
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t", budget=Budget(cap_usd=0.01))
    with pytest.raises(UnknownModelPrice, match="paid-unpriced"):
        gw.chat(MESSAGES, [], prompt_version="p")
    assert fake.calls == []


def test_pricing():
    with pytest.raises(UnknownModelPrice, match="no-such-model"):
        cost_usd("no-such-model", Usage(1, 1))
    assert cost_usd("qwen3.5:9b-q4_K_M", Usage(1000, 1000)) == 0.0


def _client(message, seen=None):
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
        model="qwen3.5:9b-q4_K_M",
    )

    def create(**kwargs):
        if seen is not None:
            seen.update(kwargs)
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_ollama_adapter_parses_tool_calls_and_sends_settings():
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="query_metric", arguments=json.dumps({"a": 1})),
            )
        ],
    )
    seen: dict = {}
    adapter = OllamaAdapter(client=_client(message, seen), digest="sha256:abc")
    result = adapter.chat(MESSAGES, [{"type": "function"}])

    assert result.tool_calls == [ToolCall("call_1", "query_metric", '{"a": 1}')]
    assert result.tool_calls[0].arguments == {"a": 1}
    assert result.usage == Usage(12, 3)
    assert seen["temperature"] == 0
    assert seen["extra_body"] == {"think": False}
    assert seen["max_tokens"] == adapter.max_tokens
    assert adapter.config()["digest"] == "sha256:abc"


def test_ollama_adapter_returns_malformed_arguments_raw():
    """Review #5: parsing must not raise inside the adapter, after a paid call, before logging."""
    bad = SimpleNamespace(
        content=None,
        tool_calls=[SimpleNamespace(id="c", function=SimpleNamespace(name="x", arguments="{oops"))],
    )
    result = OllamaAdapter(client=_client(bad), digest=None).chat(MESSAGES, [])
    assert result.usage == Usage(12, 3)
    with pytest.raises(json.JSONDecodeError):
        _ = result.tool_calls[0].arguments


def test_input_estimate_has_headroom_for_digit_heavy_json():
    """Review 2 #5: tool results full of numbers and dates tokenize at well under 3 chars/token."""
    rows = [
        {"metric_time__day": f"2026-03-{d:02d}", "complaint_count": 1000 + d} for d in range(28)
    ]
    messages = [{"role": "tool", "content": json.dumps({"rows": rows})}]
    chars = len(json.dumps([messages, []]))
    assert estimate_input_tokens(messages, []) >= chars / 1.5
