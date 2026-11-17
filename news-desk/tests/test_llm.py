from datetime import date
from types import SimpleNamespace as NS

import pytest

import budget
import config
import llm
from tests.fakes import FakeLLM

DAY = date(2026, 11, 17)


class StubAnthropic:
    def __init__(self, text=None, exc=None, blocks=None):
        self.text, self.exc, self.blocks, self.calls = text, exc, blocks, 0
        self.messages = self

    def create(self, **kw):
        self.calls += 1
        if self.exc:
            raise self.exc
        content = self.blocks or [NS(type="text", text=self.text)]
        return NS(content=content, stop_reason="end_turn", usage=NS(input_tokens=100, output_tokens=50))


class StubOpenAI:
    def __init__(self, text):
        self.text, self.kw = text, None
        self.chat = NS(completions=self)

    def create(self, **kw):
        self.kw = kw
        return NS(choices=[NS(message=NS(content=self.text))], usage=NS(prompt_tokens=10, completion_tokens=5))


def make(conn, client, provider="anthropic", model="claude-haiku-5-5", **bk):
    return llm.LLM(provider, model, client, budget.Budget(conn, **bk), today=lambda: DAY)


def test_parses_json_inside_text(conn):
    m = make(conn, StubAnthropic('Here: {"a":1}'))
    assert m.ask_json("run", "s", "u", 100) == {"a": 1}


def test_skips_thinking_blocks(conn):
    blocks = [NS(type="thinking", thinking="hmm"), NS(type="text", text='{"a":2}')]
    assert make(conn, StubAnthropic(blocks=blocks)).ask_json("run", "s", "u", 100) == {"a": 2}


def test_bad_json_returns_none(conn):
    assert make(conn, StubAnthropic("no json here")).ask_json("run", "s", "u", 100) is None


def test_provider_error_returns_none(conn):
    assert make(conn, StubAnthropic(exc=RuntimeError("boom"))).ask_json("run", "s", "u", 100) is None


def test_records_usage(conn):
    make(conn, StubAnthropic('{"a":1}')).ask_json("run", "s", "u", 100)
    row = conn.execute("SELECT job, provider, model, input_tokens, output_tokens FROM ai_usage").fetchone()
    assert tuple(row) == ("run", "anthropic", "claude-haiku-5-5", 100, 50)


def test_blocked_by_budget_makes_no_call(conn):
    client = StubAnthropic('{"a":1}')
    m = make(conn, client, cap=0.0, reserve=0.0)
    assert m.ask_json("run", "s", "u", 100) is None
    assert client.calls == 0


def test_openai_uses_json_mode_and_usage(conn):
    client = StubOpenAI('{"ok": true}')
    m = make(conn, client, provider="openai", model="gpt-x")
    assert m.ask_json("projection", "s", "u", 100) == {"ok": True}
    assert client.kw["response_format"] == {"type": "json_object"}
    assert conn.execute("SELECT input_tokens, output_tokens FROM ai_usage").fetchone()[:] == (10, 5)


def test_from_config_skips_missing_keys(conn, monkeypatch):
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "")
    monkeypatch.setattr(config, "XAI_API_KEY", "")
    out = llm.from_config(conn)
    assert len(out["validators"]) == 1
    assert out["writer"].available and out["cluster"].available


def test_from_config_no_keys_unavailable(conn, monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY"):
        monkeypatch.setattr(config, k, "")
    out = llm.from_config(conn)
    assert out["validators"] == [] and not out["writer"].available
    assert out["writer"].ask_json("run", "s", "u", 10) is None


def test_fake_llm_records_prompts():
    f = FakeLLM([{"a": 1}, RuntimeError("x"), 'x {"b":2}'])
    assert f.ask_json("run", "sys", "usr", 5) == {"a": 1}
    assert f.ask_json("run", "s", "u", 5) is None
    assert f.ask_json("run", "s", "u", 5) == {"b": 2}
    assert f.calls[0]["system"] == "sys"
