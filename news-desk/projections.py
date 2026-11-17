"""On-demand, cached outlook for a story. Speculation only; never investment advice."""
import json
import re
from datetime import datetime, timezone

SYSTEM = """You write a short, clearly speculative outlook for a news story, in the requested language.
Everything you write is speculation, not fact; use hedged wording.
Never recommend buying, selling or holding any security and never give price targets.
Use only the given story; do not add outside facts.
Reply with JSON only, in this shape:
{"watch": [{"date": "YYYY-MM-DD or null", "what": "..."}], "outcomes": ["..."], "would_change": ["..."]}"""

ADVICE = re.compile(r"(?i)\b(buy|sell|price target|comprar|vender|precio objetivo)\b")


def _strs(v) -> list[str]:
    return [x for x in v if isinstance(x, str) and x.strip()] if isinstance(v, list) else []


def _clean(data, topic: str) -> dict | None:
    if not isinstance(data, dict):
        return None
    watch = []
    for w in data.get("watch") if isinstance(data.get("watch"), list) else []:
        if not isinstance(w, dict):
            continue
        what, date = w.get("what"), w.get("date")
        if isinstance(what, str) and what.strip() and (date is None or isinstance(date, str)):
            watch.append({"date": date, "what": what})
    outcomes = _strs(data.get("outcomes"))
    if topic == "stocks":
        outcomes = [o for o in outcomes if not ADVICE.search(o)]
    would_change = _strs(data.get("would_change"))
    if not (watch or outcomes or would_change):
        return None
    return {"watch": watch, "outcomes": outcomes, "would_change": would_change}


def get(conn, llm, story_id: str, lang: str) -> dict | None:
    row = conn.execute("SELECT body_json FROM projections WHERE story_id=? AND lang=?", (story_id, lang)).fetchone()
    if row:
        return json.loads(row["body_json"])
    s = conn.execute("SELECT * FROM stories WHERE id=?", (story_id,)).fetchone()
    if s is None:
        return None
    lang = "es" if lang == "es" else "en"
    paras = [p.get(lang, "") for p in json.loads(s["summary_json"] or "[]")]
    claims = [r[0] for r in conn.execute(
        f"SELECT text_{lang} FROM claims WHERE story_id=? ORDER BY idx", (story_id,))]
    srcs = conn.execute("SELECT i.source, i.title FROM story_items si JOIN items i ON i.id=si.item_id "
                        "WHERE si.story_id=?", (story_id,)).fetchall()
    user = (f"Language: {'Spanish' if lang == 'es' else 'English'}\nHeadline: {s['headline_' + lang]}\n"
            "Summary:\n" + "\n".join(paras) + "\nClaims:\n" + "\n".join(f"- {c}" for c in claims)
            + "\nSources:\n" + "\n".join(f"- {r['source']}: {r['title']}" for r in srcs))
    body = _clean(llm.ask_json("projection", SYSTEM, user, max_tokens=4000), s["topic"])
    if body is None:
        return None
    conn.execute("INSERT OR REPLACE INTO projections VALUES (?,?,?,?)",
                 (story_id, lang, json.dumps(body), datetime.now(timezone.utc).isoformat()))
    conn.commit()
    return body
