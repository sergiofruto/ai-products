import json

import pytest

import db
import web
from tests.fakes import FakeLLM

DAY = "2026-11-17"


@pytest.fixture
def shared():
    """One in-memory connection shared by every request of a test."""
    c = db.connect(":memory:")
    c.execute("PRAGMA foreign_keys=OFF")
    yield c
    c.close()


def make_client(conn, replies=None):
    llm = FakeLLM(replies or [])
    app = web.create_app(lambda: conn, lambda: {"writer": llm})
    app.testing = True
    return app.test_client(), llm


def add_story(conn, sid="s1", topic="ai", rank=1, head_en="Chips surge", head_es="Chips suben",
              models=3, url="https://example.com/a?x=1&y=2"):
    summary = [{"en": "Para one in English.", "es": "Parrafo uno en espanol.", "sources": ["i1"]},
               {"en": "Para two.", "es": "Parrafo dos.", "sources": ["i2"]}]
    bd = {"sources": 22, "primary": 20, "agreement": 24, "reliability": 12, "freshness": 5, "total": 83, "band": "high"}
    top = [{"item_id": "i1", "source": "Reuters", "url": url, "reason": "first report"}]
    conn.execute("INSERT INTO stories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (sid, DAY, topic, rank, head_en, head_es, "One liner EN", "Una linea ES",
                  json.dumps(summary), 83, json.dumps(bd), json.dumps(top), models))
    conn.execute("INSERT OR IGNORE INTO items (id, source, kind, url, title, published, lang) VALUES (?,?,?,?,?,?,?)",
                 ("i1", "Reuters", "wire", url, "T1", "2026-11-17T08:00:00+00:00", "en"))
    conn.execute("INSERT OR IGNORE INTO items (id, source, kind, url, title, published, lang) VALUES (?,?,?,?,?,?,?)",
                 ("i2", "Blog", "press", "https://blog.example/p", "T2", "2026-11-17T09:00:00+00:00", "en"))
    conn.execute("INSERT INTO story_items VALUES (?,?)", (sid, "i1"))
    conn.execute("INSERT INTO story_items VALUES (?,?)", (sid, "i2"))
    cur = conn.execute("INSERT INTO claims (story_id, idx, text_en, text_es, verdict) VALUES (?,?,?,?,?)",
                       (sid, 0, "Claim EN", "Claim ES", "agreed"))
    conn.execute("INSERT INTO claim_votes VALUES (?,?,?)", (cur.lastrowid, "anthropic", "supported"))
    conn.execute("INSERT INTO claim_votes VALUES (?,?,?)", (cur.lastrowid, "openai", "contradicted"))
    cur = conn.execute("INSERT INTO claims (story_id, idx, text_en, text_es, verdict) VALUES (?,?,?,?,?)",
                       (sid, 1, "Claim two", "Claim dos", "unverified"))
    conn.execute("INSERT INTO claim_votes VALUES (?,?,?)", (cur.lastrowid, "anthropic", "not_found"))
    conn.commit()


def add_paper(conn, status="ok", note=""):
    conn.execute("INSERT OR REPLACE INTO papers VALUES (?,?,?,?)", (DAY, "2026-11-17T09:30:00+00:00", status, note))
    conn.commit()


def test_home_shows_columns_and_badge(shared):
    add_story(shared)
    add_paper(shared)
    r = make_client(shared)[0].get("/")
    html = r.get_data(as_text=True)
    assert r.status_code == 200
    for name in ("AI", "Tech", "Stocks", "World", "Argentina"):
        assert name in html
    assert html.index(">AI<") < html.index(">Tech<") < html.index(">Stocks<") < html.index(">World<") < html.index(">Argentina<")
    assert "Chips surge" in html and "One liner EN" in html
    assert "2 sources" in html
    assert "badge-high" in html and "83" in html
    assert DAY in html


def test_home_spanish_toggle(shared):
    add_story(shared)
    add_paper(shared)
    client = make_client(shared)[0]
    r = client.get("/?lang=es")
    html = r.get_data(as_text=True)
    assert "Chips suben" in html and "Una linea ES" in html and "Chips surge" not in html
    assert "lang=es" in r.headers.get("Set-Cookie", "")
    assert "Chips suben" in client.get("/").get_data(as_text=True)  # remembered
    assert "Chips surge" in client.get("/?lang=xx").get_data(as_text=True)  # invalid -> en


def test_empty_column_message(shared):
    add_story(shared)
    add_paper(shared)
    html = make_client(shared)[0].get("/").get_data(as_text=True)
    assert html.count("Nothing solid today") == 4


def test_partial_banner(shared):
    add_story(shared)
    add_paper(shared, "partial", "Stopped at today's cost cap")
    html = make_client(shared)[0].get("/").get_data(as_text=True)
    assert "Stopped at today&#39;s cost cap" in html and "banner" in html
    assert "Chips surge" in html


def test_no_paper_message(shared):
    html = make_client(shared)[0].get("/").get_data(as_text=True)
    assert "No paper yet. Run <code>python main.py run</code>." in html


def test_story_links_come_from_items(shared):
    add_story(shared)
    html = make_client(shared)[0].get("/story/s1").get_data(as_text=True)
    assert 'href="https://example.com/a?x=1&amp;y=2"' in html
    assert "Synthesized from 2 sources" in html and "1 min read" in html
    assert "Para one in English." in html and "Go deep" in html
    assert 'href="/story/s1/deep"' in html


def test_deep_shows_votes_and_breakdown(shared):
    add_story(shared)
    html = make_client(shared, [{"watch": [{"date": "2026-12-01", "what": "Vote"}],
                                 "outcomes": ["Maybe up"], "would_change": ["New data"]}])[0] \
        .get("/story/s1/deep").get_data(as_text=True)
    assert "✓" in html and "✗" in html
    assert "anthropic" in html and "supported" in html and "contradicted" in html
    for k in ("sources", "primary", "agreement", "reliability", "freshness"):
        assert k in html
    assert "22" in html and "83" in html
    assert "Model speculation" in html and "Maybe up" in html and "Vote" in html
    assert "first report" in html and "wire" in html
    assert "of 3 models" not in html


def test_deep_two_of_three_label(shared):
    add_story(shared, models=2)
    html = make_client(shared)[0].get("/story/s1/deep").get_data(as_text=True)
    assert "2 of 3 models" in html
    assert "Projections unavailable (cost cap or model)" in html


def test_script_in_title_is_escaped(shared):
    add_story(shared, head_en="<script>alert(1)</script>")
    add_paper(shared)
    client = make_client(shared)[0]
    for path in ("/", "/story/s1", "/story/s1/deep"):
        html = client.get(path).get_data(as_text=True)
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_unknown_story_404(shared):
    client = make_client(shared)[0]
    assert client.get("/story/nope").status_code == 404
    assert client.get("/story/nope/deep").status_code == 404
