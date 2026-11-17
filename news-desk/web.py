"""Local web UI: Home, read view, Go deep. Server-rendered; links come only from the items table."""
import json
import math
from datetime import datetime

from flask import Flask, abort, make_response, render_template, request

import config
import projections

LANGS = ("en", "es")
SYMBOLS = {"agreed": "✓", "disputed": "~", "unverified": "✗"}


def _loads(s, default):
    try:
        return json.loads(s) if s else default
    except ValueError:
        return default


def _hhmm(created_at: str) -> str:
    try:
        return datetime.fromisoformat(created_at).astimezone().strftime("%H:%M")
    except (TypeError, ValueError):
        return ""


def create_app(conn_factory, llm_factory) -> Flask:
    app = Flask(__name__)

    def lang_of() -> str:
        q = request.args.get("lang")
        if q is not None:
            return q if q in LANGS else "en"
        c = request.cookies.get("lang")
        return c if c in LANGS else "en"

    def page(template: str, lang: str, **ctx):
        resp = make_response(render_template(template, lang=lang, path=request.path, **ctx))
        if request.args.get("lang") is not None:
            resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="Lax")
        return resp

    def story_or_404(conn, sid):
        s = conn.execute("SELECT * FROM stories WHERE id=?", (sid,)).fetchone()
        if s is None:
            abort(404)
        return s

    def sources_of(conn, sid):
        return conn.execute(
            "SELECT i.id, i.source, i.kind, i.url, i.title, i.published FROM story_items si "
            "JOIN items i ON i.id=si.item_id WHERE si.story_id=? ORDER BY i.published, i.id", (sid,)).fetchall()

    @app.get("/")
    def home():
        conn, lang = conn_factory(), lang_of()
        day_row = conn.execute("SELECT MAX(day) FROM stories").fetchone()
        day = day_row[0] if day_row else None
        paper = conn.execute("SELECT * FROM papers ORDER BY day DESC LIMIT 1").fetchone()
        banner = paper["note"] if paper and paper["status"] in ("partial", "failed") else None
        if banner is not None and not banner:
            banner = f"Paper status: {paper['status']}"
        cols = []
        if day:
            for key, name in config.TOPICS:
                rows = conn.execute(
                    "SELECT s.*, (SELECT COUNT(*) FROM story_items si WHERE si.story_id=s.id) AS n_sources "
                    "FROM stories s WHERE day=? AND topic=? ORDER BY rank", (day, key)).fetchall()
                cols.append({"key": key, "name": name, "stories": [
                    {"id": r["id"], "headline": r["headline_" + lang], "oneliner": r["oneliner_" + lang],
                     "n_sources": r["n_sources"], "score": r["score"],
                     "band": _loads(r["breakdown_json"], {}).get("band", "low")} for r in rows]})
        pr = conn.execute("SELECT * FROM papers WHERE day=?", (day,)).fetchone() if day else None
        updated = _hhmm(pr["created_at"]) if pr else ""
        return page("home.html", lang, day=day, cols=cols, banner=banner, updated=updated)

    @app.get("/story/<sid>")
    def story(sid):
        conn, lang = conn_factory(), lang_of()
        s = story_or_404(conn, sid)
        by_id = {r["id"]: r for r in sources_of(conn, sid)}
        paras = []
        for p in _loads(s["summary_json"], []):
            srcs = [by_id[i] for i in p.get("sources", []) if i in by_id]
            paras.append({"text": p.get(lang, ""), "sources": srcs})
        words = sum(len(p["text"].split()) for p in paras)
        return page("story.html", lang, s=s, headline=s["headline_" + lang], paras=paras,
                    n_sources=len(by_id), minutes=max(1, math.ceil(words / 200)))

    @app.get("/story/<sid>/deep")
    def deep(sid):
        conn, lang = conn_factory(), lang_of()
        s = story_or_404(conn, sid)
        sources = sources_of(conn, sid)
        by_id = {r["id"]: r for r in sources}
        top = [t for t in _loads(s["top_sources_json"], []) if isinstance(t, dict)]
        top_view = [{"source": by_id[t["item_id"]]["source"], "kind": by_id[t["item_id"]]["kind"],
                     "url": by_id[t["item_id"]]["url"],
                     "reason": t.get("reason", "")} for t in top[:3] if t.get("item_id") in by_id]
        rest = [r for r in sources if r["id"] not in {t["item_id"] for t in top[:3] if "item_id" in t}]
        claims = []
        for c in conn.execute("SELECT * FROM claims WHERE story_id=? ORDER BY idx", (sid,)):
            votes = conn.execute("SELECT provider, vote FROM claim_votes WHERE claim_id=? ORDER BY provider",
                                 (c["id"],)).fetchall()
            claims.append({"text": c["text_" + lang], "verdict": c["verdict"],
                           "symbol": SYMBOLS.get(c["verdict"], "?"), "votes": votes})
        paras = [{"text": p.get(lang, ""), "sources": [by_id[i] for i in p.get("sources", []) if i in by_id]}
                 for p in _loads(s["summary_json"], [])]
        bd = _loads(s["breakdown_json"], {})
        rows = [(k, bd.get(k, 0)) for k in ("sources", "primary", "agreement", "reliability", "freshness")]
        proj = projections.get(conn, llm_factory()["writer"], sid, lang)
        return page("deep.html", lang, s=s, headline=s["headline_" + lang], paras=paras, sources=sources,
                    claims=claims, models=s["models_answered"], breakdown=rows, total=bd.get("total", s["score"]),
                    band=bd.get("band", "low"), proj=proj, top=top_view, rest=rest)

    return app
