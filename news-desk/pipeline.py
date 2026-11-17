"""The daily run: fetch, cluster, write, validate, score, persist, export."""
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import budget as budget_mod
import cluster
import config
import export
import rules
import validate
import write

log = logging.getLogger("news_desk.pipeline")


def _fail(conn: sqlite3.Connection, day: str, now: datetime, note: str) -> dict:
    """Failed run: leave an existing day untouched, else record a failed paper."""
    if not conn.execute("SELECT 1 FROM stories WHERE day=? LIMIT 1", (day,)).fetchone():
        conn.execute("INSERT OR REPLACE INTO papers VALUES (?,?,?,?)", (day, now.isoformat(), "failed", note))
        conn.commit()
    return {"status": "failed", "stories": 0, "note": note}


def _queue(llm, items) -> list[tuple[str, list]]:
    """Round-robin across topics by rank, up to STORIES_PER_TOPIC each."""
    ranked = {}
    for key, _ in config.TOPICS:
        topic_items = [i for i in items if i.topic == key]
        ranked[key] = cluster.cluster(llm, key, topic_items)[:config.STORIES_PER_TOPIC] if topic_items else []
    queue = []
    for r in range(config.STORIES_PER_TOPIC):
        for key, _ in config.TOPICS:
            if r < len(ranked[key]):
                queue.append((key, ranked[key][r]))
    return queue


def run(conn: sqlite3.Connection, now: datetime, llms: dict, fetch_fn,
        budget: budget_mod.Budget | None = None) -> dict:
    now = now.astimezone()  # the paper day is the local date (ruling R8)
    dt = now.date()
    day = dt.isoformat()
    budget = budget or budget_mod.Budget(conn)

    all_llms = [llms["writer"], llms["cluster"], *llms["validators"]]
    saved = [(m, m.__dict__.get("today")) for m in all_llms]
    for m in all_llms:  # every model checks and records against the same day for the whole run
        m.today = lambda: dt
    try:
        return _run(conn, now, dt, day, llms, fetch_fn, budget)
    finally:
        for m, old in saved:
            if old is None:
                m.__dict__.pop("today", None)
            else:
                m.today = old


def _run(conn, now, dt, day, llms, fetch_fn, budget) -> dict:
    items = fetch_fn()
    if not items:
        return _fail(conn, day, now, "No items fetched")
    if not llms["writer"].available:
        return _fail(conn, day, now, "Writer model unavailable")

    by_id = {i.id: i for i in items}
    built, per_topic, capped = [], {}, False
    for topic, group in _queue(llms["cluster"], items):
        if not budget.can_spend("run", dt):
            capped = True
            break
        draft = write.write_story(llms["writer"], group)
        if draft is None:
            if not budget.can_spend("run", dt):  # a budget refusal looks like a malformed draft
                capped = True
                break
            log.info("story skipped (no valid draft) topic=%s", topic)
            continue
        verdicts, votes = validate.check(llms["validators"], draft.claims, group)
        answered = len(votes)
        if answered < sum(1 for v in llms["validators"] if v.available) and not budget.can_spend("run", dt):
            capped = True  # validation was cut by the cap: a smaller paper beats an unvalidated story
            break
        breakdown = rules.score(
            independent=rules.independent_count(group), has_primary=any(i.kind == "primary" for i in group),
            verdicts=verdicts, models_answered=answered,
            avg_reliability=sum(i.reliability for i in group) / len(group), corrected=False)
        per_topic[topic] = per_topic.get(topic, 0) + 1
        built.append({"topic": topic, "rank": per_topic[topic], "items": group, "draft": draft,
                      "verdicts": verdicts, "votes": votes, "breakdown": breakdown,
                      "top": rules.top_sources(group)})

    if not built:
        return _fail(conn, day, now, "Stopped at today's cost cap" if capped else "No stories produced")

    status = "partial" if capped else "ok"
    note = "Stopped at today's cost cap" if capped else ""
    with conn:  # one transaction: a crash leaves the old day intact
        ids = [r[0] for r in conn.execute("SELECT id FROM stories WHERE day=?", (day,))]
        for sid in ids:
            conn.execute("DELETE FROM claim_votes WHERE claim_id IN (SELECT id FROM claims WHERE story_id=?)", (sid,))
            for t in ("claims", "story_items"):
                conn.execute(f"DELETE FROM {t} WHERE story_id=?", (sid,))
            conn.execute("DELETE FROM projections WHERE story_id=?", (sid,))
        conn.execute("DELETE FROM stories WHERE day=?", (day,))
        for i in items:
            conn.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (i.id, day, i.topic, i.source, i.kind, i.url, i.host, i.title, i.published.isoformat(),
                          i.text, i.lang, i.reliability, i.wire))
        for b in built:
            d, sid = b["draft"], f"{day}-{b['topic']}-{b['rank']}"
            conn.execute("INSERT INTO stories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (sid, day, b["topic"], b["rank"], d.headline["en"], d.headline["es"],
                          d.oneliner["en"], d.oneliner["es"], json.dumps(d.summary, ensure_ascii=False),
                          b["breakdown"]["total"], json.dumps(b["breakdown"]),
                          json.dumps(b["top"], ensure_ascii=False), len(b["votes"])))
            for i in b["items"]:
                conn.execute("INSERT INTO story_items VALUES (?,?)", (sid, by_id[i.id].id))
            for idx, c in enumerate(d.claims):
                cur = conn.execute("INSERT INTO claims (story_id, idx, text_en, text_es, verdict) VALUES (?,?,?,?,?)",
                                   (sid, idx, c["en"], c["es"], b["verdicts"][idx]))
                for provider, v in b["votes"].items():
                    conn.execute("INSERT INTO claim_votes VALUES (?,?,?)", (cur.lastrowid, provider, v[idx]))
        conn.execute("INSERT OR REPLACE INTO papers VALUES (?,?,?,?)", (day, now.isoformat(), status, note))

    export.write(conn, day, Path(config.EXPORT_DIR))
    return {"status": status, "stories": len(built), "note": note}
