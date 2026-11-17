"""SQLite schema and connection."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS items(id TEXT PRIMARY KEY, day TEXT, topic TEXT, source TEXT, kind TEXT, url TEXT,
    host TEXT, title TEXT, published TEXT, text TEXT, lang TEXT, reliability REAL, wire TEXT);
CREATE TABLE IF NOT EXISTS papers(day TEXT PRIMARY KEY, created_at TEXT, status TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS stories(id TEXT PRIMARY KEY, day TEXT, topic TEXT, rank INTEGER,
    headline_en TEXT, headline_es TEXT, oneliner_en TEXT, oneliner_es TEXT,
    summary_json TEXT, score INTEGER, breakdown_json TEXT, top_sources_json TEXT, models_answered INTEGER);
CREATE TABLE IF NOT EXISTS story_items(story_id TEXT, item_id TEXT);
CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY, story_id TEXT, idx INTEGER, text_en TEXT,
    text_es TEXT, verdict TEXT);
CREATE TABLE IF NOT EXISTS claim_votes(claim_id INTEGER, provider TEXT, vote TEXT);
CREATE TABLE IF NOT EXISTS projections(story_id TEXT, lang TEXT, body_json TEXT, created_at TEXT,
    PRIMARY KEY(story_id, lang));
CREATE TABLE IF NOT EXISTS ai_usage(day TEXT, job TEXT, provider TEXT, model TEXT, input_tokens INTEGER,
    output_tokens INTEGER, cost_usd REAL);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn
