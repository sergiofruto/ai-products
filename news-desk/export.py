"""Export a day's paper to markdown and JSON. Links come from the items table only."""
import json
import sqlite3
from pathlib import Path

import config
import rules


def _load(conn: sqlite3.Connection, day: str) -> dict:
    paper = conn.execute("SELECT status, note FROM papers WHERE day=?", (day,)).fetchone()
    topics = []
    for key, display in config.TOPICS:
        stories = []
        for s in conn.execute("SELECT * FROM stories WHERE day=? AND topic=? ORDER BY rank", (day, key)):
            claims = []
            for c in conn.execute("SELECT * FROM claims WHERE story_id=? ORDER BY idx", (s["id"],)):
                claims.append({"en": c["text_en"], "es": c["text_es"], "verdict": c["verdict"]})
            sources = [dict(r) for r in conn.execute(
                "SELECT i.id, i.source, i.title, i.url FROM story_items si JOIN items i ON i.id = si.item_id "
                "WHERE si.story_id=? ORDER BY i.published, i.id", (s["id"],))]
            breakdown = json.loads(s["breakdown_json"])
            stories.append({
                "id": s["id"], "rank": s["rank"],
                "headline": {"en": s["headline_en"], "es": s["headline_es"]},
                "oneliner": {"en": s["oneliner_en"], "es": s["oneliner_es"]},
                "summary": json.loads(s["summary_json"]),
                "score": s["score"], "band": breakdown.get("band", rules.band_for(s["score"])),
                "breakdown": breakdown, "models_answered": s["models_answered"],
                "claims": claims, "sources": sources,
                "top_sources": json.loads(s["top_sources_json"]),
            })
        topics.append({"key": key, "name": display, "stories": stories})
    return {"day": day, "status": paper["status"] if paper else None,
            "note": paper["note"] if paper else None, "topics": topics}


def _markdown(data: dict) -> str:
    out = [f"# News Desk, {data['day']}", ""]
    if data["status"] and data["status"] != "ok":
        out += [f"_Status: {data['status']}. {data['note']}_", ""]
    for t in data["topics"]:
        out += [f"## {t['name']}", ""]
        if not t["stories"]:
            out += ["_No stories._", ""]
        for s in t["stories"]:
            out += [f"### {s['headline']['en']}", "", f"Score: {s['score']} ({s['band']})", "",
                    s["oneliner"]["en"], "", "Claims:"]
            out += [f"- {c['en']} [{c['verdict']}]" for c in s["claims"]]
            out += ["", "Sources:"]
            out += [f"- [{x['source']}]({x['url']})" for x in s["sources"]]
            out.append("")
    return "\n".join(out)


def write(conn: sqlite3.Connection, day: str, out_dir: Path) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = _load(conn, day)
    md, js = out_dir / f"{day}.md", out_dir / f"{day}.json"
    md.write_text(_markdown(data), encoding="utf-8")
    js.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return md, js
