import json
from types import SimpleNamespace

import duckdb
import pytest

from agent.adapters.base import ChatResult, ToolCall, Usage
from agent.adapters.cache import JsonCache
from agent.adapters.fake import FakeAdapter
from agent.adapters.gateway import Budget, BudgetExceeded, Gateway
from agent.adapters.ollama import OllamaAdapter
from agent.adapters.pricing import cost_usd
from agent.adapters.usage import UsageLog

MESSAGES = [{"role": "user", "content": "hi"}]


def _result(text: str = "hello", tin: int = 10, tout: int = 5) -> ChatResult:
    return ChatResult(content=text, tool_calls=[], usage=Usage(tin, tout), model="fake")


@pytest.fixture
def gateway_parts(tmp_path):
    usage = UsageLog(tmp_path / "usage.duckdb")
    cache = JsonCache(tmp_path / "cache")
    return usage, cache


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


def test_gateway_logs_usage_and_caches(gateway_parts):
    usage, cache = gateway_parts
    fake = FakeAdapter([_result()])
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t1")

    first = gw.chat(MESSAGES, [], prompt_version="system.v1")
    second = gw.chat(MESSAGES, [], prompt_version="system.v1")  # same input -> cache

    assert first == second
    assert len(fake.calls) == 1
    assert _usage_rows(usage) == [
        ("fake", "system.v1", 10, 5, 0.0, False, "t1"),
        ("fake", "system.v1", 0, 0, 0.0, True, "t1"),
    ]


def test_cache_key_includes_prompt_version(gateway_parts):
    usage, cache = gateway_parts
    fake = FakeAdapter([_result("v1"), _result("v2")])
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t")
    assert gw.chat(MESSAGES, [], prompt_version="system.v1").content == "v1"
    assert gw.chat(MESSAGES, [], prompt_version="system.v2").content == "v2"


def test_budget_refuses_call_once_cap_reached(gateway_parts, monkeypatch):
    usage, cache = gateway_parts
    monkeypatch.setattr("agent.adapters.gateway.cost_usd", lambda model, u: 0.6)
    fake = FakeAdapter([_result("a"), _result("b"), _result("c")])
    gw = Gateway(fake, usage=usage, cache=cache, run_id="t", budget=Budget(cap_usd=1.0))
    gw.chat([{"role": "user", "content": "1"}], [], prompt_version="p")
    gw.chat([{"role": "user", "content": "2"}], [], prompt_version="p")  # spent 1.2 after this
    with pytest.raises(BudgetExceeded, match="1.20"):
        gw.chat([{"role": "user", "content": "3"}], [], prompt_version="p")
    assert len(fake.calls) == 2


def test_unknown_model_price_fails_loudly():
    with pytest.raises(KeyError, match="no-such-model"):
        cost_usd("no-such-model", Usage(1, 1))
    assert cost_usd("qwen3.5:9b-q4_K_M", Usage(1000, 1000)) == 0.0


def test_ollama_adapter_parses_tool_calls():
    message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(name="query_metric", arguments=json.dumps({"a": 1})),
            )
        ],
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=message)],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3),
        model="qwen3.5:9b-q4_K_M",
    )
    seen = {}

    def create(**kwargs):
        seen.update(kwargs)
        return response

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    adapter = OllamaAdapter(client=client)
    result = adapter.chat(MESSAGES, [{"type": "function"}])

    assert result.tool_calls == [ToolCall(id="call_1", name="query_metric", arguments={"a": 1})]
    assert result.usage == Usage(12, 3)
    assert seen["temperature"] == 0 and seen["extra_body"] == {"think": False}


def test_ollama_adapter_rejects_malformed_tool_arguments():
    bad = SimpleNamespace(
        content=None,
        tool_calls=[SimpleNamespace(id="c", function=SimpleNamespace(name="x", arguments="{oops"))],
    )
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=bad)],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
        model="m",
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: response))
    )
    with pytest.raises(json.JSONDecodeError):
        OllamaAdapter(client=client).chat(MESSAGES, [])
