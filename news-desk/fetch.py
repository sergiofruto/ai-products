"""Fetch candidate news items from RSS/Atom feeds. Facts only: no summarising, no judging.

Every network access goes through the injected `get` (default requests.get) so tests stay offline.
"""
import hashlib
import html
import logging
import re
from calendar import timegm
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import feedparser
import requests
import trafilatura
import yaml

from models import Item

logger = logging.getLogger("news_desk.fetch")

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT, "Accept": "*/*"}
TIMEOUT = 15
SHORT_SUMMARY = 400
MAX_TEXT = 6000

WIRE_PATTERNS = [
    ("reuters", re.compile(r"\bReuters\b", re.I)),
    ("ap", re.compile(r"\(AP\)|\bAssociated Press\b")),
    ("afp", re.compile(r"\(AFP\)|\bAFP\b")),
    ("efe", re.compile(r"\(EFE\)|\bAgencia EFE\b")),
    ("noticias argentinas", re.compile(r"\(NA\)|\bAgencia NA\b|\bNoticias Argentinas\b")),
]


def detect_wire(text: str) -> str | None:
    for name, pat in WIRE_PATTERNS:
        if pat.search(text or ""):
            return name
    return None


def load_sources(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["sources"] if isinstance(data, dict) else data


def item_id(url: str, topic: str) -> str:
    return hashlib.sha1(f"{url}|{topic}".encode()).hexdigest()[:12]


def host_of(url: str) -> str:
    h = urlparse(url).hostname or ""
    return h[4:] if h.startswith("www.") else h


_DROP_BLOCKS = re.compile(r"<(script|style)\b[^>]*>.*?</\1\s*>", re.I | re.S)


def _plain(s: str) -> str:
    s = _DROP_BLOCKS.sub(" ", html.unescape(s or ""))
    s = _DROP_BLOCKS.sub(" ", s)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", s)).strip()


class _Robots:
    """robots.txt per host, fetched through `get`; any failure means allowed."""

    def __init__(self, get):
        self.get, self.cache = get, {}

    def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            rp = None
            try:
                r = self.get(base + "/robots.txt", headers=HEADERS, timeout=TIMEOUT)
                r.raise_for_status()
                rp = RobotFileParser()
                rp.parse(r.text.splitlines())
            except Exception:
                rp = None
            self.cache[base] = rp
        rp = self.cache[base]
        try:
            return True if rp is None else rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True


def _page_text(url: str, get, robots: _Robots) -> str | None:
    try:
        if not robots.allowed(url):
            return None
        r = get(url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
        return trafilatura.extract(r.text) or None
    except Exception as e:
        logger.info("page fetch failed %s: %s", url, type(e).__name__)
        return None


def _published(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    return datetime.fromtimestamp(timegm(t), tz=timezone.utc) if t else None


def _entries(src: dict, now: datetime, get, robots: _Robots, window_hours: int) -> list[Item]:
    r = get(src["url"], headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    feed = feedparser.parse(r.content)
    since = now - timedelta(hours=window_hours)
    out = []
    for e in feed.entries:
        url = (e.get("link") or "").strip()
        pub = _published(e)
        if not url or pub is None or pub < since or pub > now + timedelta(hours=1):
            continue
        title = _plain(e.get("title", ""))
        if not title:
            continue
        body = e.get("summary") or ""
        if e.get("content"):
            body = max([c.get("value", "") for c in e["content"]] + [body], key=len)
        text = _plain(body)
        if len(text) < SHORT_SUMMARY:
            full = _page_text(url, get, robots)
            if full:
                text = _plain(full)
        text = text[:MAX_TEXT]
        wire = detect_wire(f"{title} {text}")
        for topic in src["topics"]:
            out.append(Item(item_id(url, topic), topic, src["name"], src["kind"], url, host_of(url),
                            title, pub, text, src["lang"], float(src["reliability"]), wire))
    return out


def fetch_all(sources: list[dict], now: datetime, get=requests.get, window_hours: int = 24) -> list[Item]:
    robots = _Robots(get)
    items: list[Item] = []
    for src in sources:
        try:
            items.extend(_entries(src, now, get, robots, window_hours))
        except Exception as e:
            logger.warning("feed skipped %s: %s", src.get("name"), type(e).__name__)
    return items
