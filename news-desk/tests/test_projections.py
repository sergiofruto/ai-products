import json

import projections
from tests.fakes import FakeLLM

GOOD = {"watch": [{"date": "2026-12-01", "what": "Vote"}, {"date": None, "what": "Follow-up"}, {"what": ""}],
        "outcomes": ["A may happen", "", 5], "would_change": ["New data"]}


def seed(conn, topic="ai"):
    conn.execute("INSERT INTO stories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 ("s1", "2026-11-17", topic, 1, "Head EN", "Titular ES", "one", "uno",
                  json.dumps([{"en": "Para EN", "es": "Parrafo ES", "sources": ["i1"]}]), 80, "{}", "[]", 3))
    conn.execute("INSERT INTO items (id, source, title, text) VALUES ('i1','Wire','Item title','t')")
    conn.execute("INSERT INTO story_items VALUES ('s1','i1')")
    conn.execute("INSERT INTO claims (story_id, idx, text_en, text_es, verdict) VALUES ('s1',0,'Claim EN','Claim ES','ok')")
    conn.commit()


def test_generates_and_caches(conn):
    seed(conn)
    llm = FakeLLM([GOOD])
    out = projections.get(conn, llm, "s1", "en")
    assert out == {"watch": [{"date": "2026-12-01", "what": "Vote"}, {"date": None, "what": "Follow-up"}],
                   "outcomes": ["A may happen"], "would_change": ["New data"]}
    assert llm.calls[0]["job"] == "projection" and "Head EN" in llm.calls[0]["user"] and "Wire" in llm.calls[0]["user"]
    assert projections.get(conn, llm, "s1", "en") == out
    assert len(llm.calls) == 1
    assert projections.get(conn, FakeLLM([]), "nope", "en") is None


def test_budget_blocked_returns_none(conn):
    seed(conn)
    llm = FakeLLM([None])
    assert projections.get(conn, llm, "s1", "en") is None
    assert conn.execute("SELECT COUNT(*) FROM projections").fetchone()[0] == 0


def test_stocks_advice_lines_removed(conn):
    seed(conn, "stocks")
    reply = {"watch": [], "outcomes": ["Investors should BUY now", "Price target 200", "Guidance may slip",
                                       "Comprar acciones"], "would_change": []}
    out = projections.get(conn, FakeLLM([reply]), "s1", "en")
    assert out["outcomes"] == ["Guidance may slip"]


def test_prompt_contains_guardrail(conn):
    seed(conn)
    llm = FakeLLM([GOOD])
    projections.get(conn, llm, "s1", "es")
    s = llm.calls[0]["system"].lower()
    assert "speculation" in s and "buying, selling or holding" in s and "price targets" in s
    assert "Titular ES" in llm.calls[0]["user"]
