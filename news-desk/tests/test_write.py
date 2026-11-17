from datetime import datetime, timezone

import write
from models import Item
from tests.fakes import FakeLLM

T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def mk(id):
    return Item(id=id, topic="ai", source="Src", kind="outlet", url=f"https://x.com/{id}", host="x.com",
                title=f"title {id}", published=T0, text="body " + id, lang="en", reliability=0.5)


def bi(t):
    return {"en": t, "es": t + " es"}


def reply(summary=None, claims=None, **over):
    r = {
        "headline": bi("H"),
        "oneliner": bi("O"),
        "summary": summary if summary is not None else [{"en": "p", "es": "p es", "sources": ["a", "b"]}],
        "claims": claims if claims is not None else [bi("c1"), bi("c2"), bi("c3")],
    }
    r.update(over)
    return r


ITEMS = [mk("a"), mk("b")]


def test_valid_draft():
    llm = FakeLLM([reply()])
    d = write.write_story(llm, ITEMS)
    assert d.headline == bi("H") and d.oneliner == bi("O")
    assert d.summary == [{"en": "p", "es": "p es", "sources": ["a", "b"]}]
    assert len(d.claims) == 3
    call = llm.calls[0]
    assert call["job"] == "run" and call["max_tokens"] >= 8000
    assert "a: Src — title a — body a" in call["user"]
    assert "price target" in call["system"]


def test_unknown_source_ids_removed():
    s = [{"en": "p", "es": "p es", "sources": ["a", "zzz", 5, None, "b"]}]
    d = write.write_story(FakeLLM([reply(summary=s)]), ITEMS)
    assert d.summary[0]["sources"] == ["a", "b"]


def test_paragraph_without_valid_sources_dropped():
    s = [{"en": "p", "es": "p es", "sources": ["zzz"]}, {"en": "q", "es": "q es", "sources": ["a"]}]
    d = write.write_story(FakeLLM([reply(summary=s)]), ITEMS)
    assert [p["en"] for p in d.summary] == ["q"]


def test_all_paragraphs_invalid_returns_none():
    s = [{"en": "p", "es": "p es", "sources": ["zzz"]}]
    assert write.write_story(FakeLLM([reply(summary=s)]), ITEMS) is None


def test_claims_capped_at_six():
    claims = [bi(f"c{i}") for i in range(9)]
    d = write.write_story(FakeLLM([reply(claims=claims)]), ITEMS)
    assert len(d.claims) == 6


def test_missing_spanish_returns_none():
    assert write.write_story(FakeLLM([reply(headline={"en": "H", "es": ""})]), ITEMS) is None
    assert write.write_story(FakeLLM([reply(oneliner={"en": "O"})]), ITEMS) is None
    s = [{"en": "p", "sources": ["a"]}]
    assert write.write_story(FakeLLM([reply(summary=s)]), ITEMS) is None
    assert write.write_story(FakeLLM([reply(claims=[{"en": "c"}])]), ITEMS) is None


def test_model_failure_returns_none():
    assert write.write_story(FakeLLM([RuntimeError("x")]), ITEMS) is None
    assert write.write_story(FakeLLM([{"junk": 1}]), ITEMS) is None
