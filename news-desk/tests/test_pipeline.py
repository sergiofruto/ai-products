import json
from datetime import datetime, timezone

import pipeline
from models import Item
from tests.fakes import FakeLLM

NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
DAY = "2026-11-17"


def mk(id, topic, host=None):
    return Item(id=id, topic=topic, source="Src " + id, kind="primary", url=f"https://{host or id}.com/{id}",
                host=host or f"{id}.com", title=f"title {id}", published=NOW, text="body " + id, lang="en",
                reliability=0.8)


def draft(h):
    return {"headline": {"en": h, "es": h + " es"}, "oneliner": {"en": "one " + h, "es": "uno " + h},
            "summary": [{"en": "p", "es": "p es", "sources": []}],
            "claims": [{"en": "c1", "es": "c1 es"}, {"en": "c2", "es": "c2 es"}, {"en": "c3", "es": "c3 es"}]}


def draft_for(item_ids, h):
    d = draft(h)
    d["summary"][0]["sources"] = item_ids
    return d


class Budget:
    """Allows `n` writer calls in total; spend is observed from the writer's call count."""

    def __init__(self, l, n):
        self.l, self.n = l, n

    def can_spend(self, job, day):
        return len(self.l["writer"].calls) < self.n


def votes(v="supported"):
    return {"votes": [v, v, v]}


def llms(writer_replies, n_validators=2):
    return {"writer": FakeLLM(writer_replies), "cluster": FakeLLM([]),
            "validators": [FakeLLM([votes()] * 10, provider=f"p{i}") for i in range(n_validators)]}


ITEMS = [mk("a1", "ai"), mk("a2", "ai"), mk("t1", "tech"), mk("t2", "tech")]


def run(conn, l, items=ITEMS, **kw):
    return pipeline.run(conn, NOW, l, lambda: list(items), **kw)


def test_end_to_end_two_topics(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l = llms([draft_for(["a1"], "AI head"), draft_for(["t1"], "Tech head"),
              draft_for(["a2"], "AI two"), draft_for(["t2"], "Tech two")])
    r = run(conn, l)
    assert r["status"] == "ok" and r["stories"] == 4
    assert conn.execute("SELECT status FROM papers WHERE day=?", (DAY,)).fetchone()[0] == "ok"
    assert conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 12
    assert conn.execute("SELECT COUNT(*) FROM claim_votes").fetchone()[0] == 24
    assert conn.execute("SELECT COUNT(*) FROM items WHERE day=?", (DAY,)).fetchone()[0] == 4
    s = conn.execute("SELECT * FROM stories WHERE id=?", (f"{DAY}-ai-1",)).fetchone()
    assert s["headline_en"] == "AI head" and s["models_answered"] == 2
    assert json.loads(s["breakdown_json"])["total"] == s["score"]
    md, js = tmp_path / f"{DAY}.md", tmp_path / f"{DAY}.json"
    assert "AI head" in md.read_text() and "Tech head" in md.read_text()
    assert json.loads(js.read_text())["day"] == DAY


def test_round_robin_order(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l = llms([draft_for(["a1"], "AI1"), draft_for(["t1"], "T1")])
    r = run(conn, l, budget=Budget(l, 2))
    assert r["status"] == "partial" and r["note"] == "Stopped at today's cost cap"
    rows = {x[0] for x in conn.execute("SELECT id FROM stories")}
    assert rows == {f"{DAY}-ai-1", f"{DAY}-tech-1"}


def test_budget_stop_is_partial_and_keeps_done_stories(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l = llms([draft_for(["a1"], "X")])
    r = run(conn, l, budget=Budget(l, 1))
    assert r["status"] == "partial" and r["stories"] == 1
    assert conn.execute("SELECT status FROM papers WHERE day=?", (DAY,)).fetchone()[0] == "partial"
    assert conn.execute("SELECT COUNT(*) FROM stories").fetchone()[0] == 1


def test_missing_writer_keeps_previous_paper(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l0 = llms([draft_for(["a1"], "A"), draft_for(["t1"], "B")])
    run(conn, l0, budget=Budget(l0, 2))
    before = [tuple(r) for r in conn.execute("SELECT id, headline_en FROM stories ORDER BY id")]
    l = llms([])
    l["writer"].available = False
    r = run(conn, l)
    assert r["status"] == "failed" and r["note"] == "Writer model unavailable"
    assert [tuple(r) for r in conn.execute("SELECT id, headline_en FROM stories ORDER BY id")] == before
    assert conn.execute("SELECT status FROM papers WHERE day=?", (DAY,)).fetchone()[0] != "failed"


def test_failed_without_existing_day_records_failed_paper(conn):
    l = llms([])
    l["writer"].available = False
    assert run(conn, l)["status"] == "failed"
    assert conn.execute("SELECT status, note FROM papers WHERE day=?", (DAY,)).fetchone()[:] == (
        "failed", "Writer model unavailable")
    r = run(conn, llms([]), items=[])
    assert r["status"] == "failed" and r["note"] == "No items fetched"


def test_rerun_replaces_day(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l0 = llms([draft_for(["a1"], "Old1"), draft_for(["t1"], "Old2")])
    run(conn, l0, budget=Budget(l0, 2))
    l1 = llms([draft_for(["a1"], "New1")])
    run(conn, l1, budget=Budget(l1, 1))
    heads = [r[0] for r in conn.execute("SELECT headline_en FROM stories")]
    assert heads == ["New1"]
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 3
    assert conn.execute("SELECT COUNT(*) FROM claim_votes").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM story_items").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 1


def test_story_skipped_when_write_returns_none(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l = llms([{"bad": 1}, draft_for(["t1"], "T1")])
    r = run(conn, l, budget=Budget(l, 3))
    assert r["stories"] == 1
    assert [x[0] for x in conn.execute("SELECT headline_en FROM stories")] == ["T1"]


def test_writer_refused_by_budget_is_partial_keeps_earlier(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l = llms([draft_for(["a1"], "AI1")])  # second writer call returns None, as a refusal would
    r = run(conn, l, budget=Budget(l, 2))
    assert r["status"] == "partial" and r["note"] == "Stopped at today's cost cap" and r["stories"] == 1
    assert [x[0] for x in conn.execute("SELECT headline_en FROM stories")] == ["AI1"]


def test_cap_between_writer_and_validators_drops_that_story(conn, tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    l = llms([draft_for(["a1"], "AI1"), draft_for(["t1"], "T1")])
    for v in l["validators"]:
        v.replies = [votes()]  # second story's validators are refused
    r = run(conn, l, budget=Budget(l, 2))
    assert r["status"] == "partial" and r["stories"] == 1
    assert [x[0] for x in conn.execute("SELECT headline_en FROM stories")] == ["AI1"]
    assert conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 3


def test_day_is_local_date_for_paper_and_budget(conn, tmp_path, monkeypatch):
    import time
    from types import SimpleNamespace

    import budget as budget_mod
    import config
    import llm as llm_mod
    monkeypatch.setattr(config, "EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("TZ", "America/Argentina/Buenos_Aires")
    time.tzset()
    try:
        text = json.dumps(draft_for(["a1"], "Local"))
        msg = SimpleNamespace(usage=SimpleNamespace(input_tokens=100, output_tokens=50), stop_reason="end_turn",
                              content=[SimpleNamespace(type="text", text=text)])
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: msg))
        b = budget_mod.Budget(conn)
        l = llms([])
        l["writer"] = llm_mod.LLM("anthropic", "claude-sonnet-5-5", client, b, today=lambda: __import__("datetime").date(2000, 1, 1))
        now = datetime(2026, 11, 17, 1, tzinfo=timezone.utc)  # 22:00 on the 16th in Buenos Aires
        r = pipeline.run(conn, now, l, lambda: [mk("a1", "ai")])
    finally:
        monkeypatch.undo()
        time.tzset()
    assert r["status"] == "ok"
    assert conn.execute("SELECT day FROM papers").fetchone()[0] == "2026-11-16"
    assert [x[0] for x in conn.execute("SELECT DISTINCT day FROM stories")] == ["2026-11-16"]
    assert [x[0] for x in conn.execute("SELECT DISTINCT day FROM ai_usage")] == ["2026-11-16"]
    assert (tmp_path / "2026-11-16.md").exists()
