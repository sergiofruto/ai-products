from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

import fetch

FIX = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


class Resp:
    def __init__(self, content: bytes, status=200):
        self.content, self.status_code = content, status
        self.text = content.decode("utf-8", "replace")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def src(name="S", url="https://feed.example/rss", topics=("ai",), **kw):
    d = dict(name=name, url=url, topics=list(topics), kind="outlet", reliability=0.7, lang="en", reason="r")
    d.update(kw)
    return d


def getter(mapping):
    def get(url, **kw):
        v = mapping.get(url)
        if isinstance(v, Exception):
            raise v
        return Resp(v if v is not None else b"", 200 if v is not None else 404)
    return get


def test_parses_feed_within_window():
    get = getter({"https://feed.example/rss": (FIX / "feed_ok.xml").read_bytes()})
    items = fetch.fetch_all([src(kind="wire", reliability=0.9, lang="es")], NOW, get=get)
    assert len(items) == 2
    for it in items:
        assert (it.topic, it.kind, it.reliability, it.lang, it.source) == ("ai", "wire", 0.9, "es", "S")
        assert it.host == "example.com"
        assert it.published.tzinfo is not None
    assert {i.url for i in items} == {"https://www.example.com/a", "https://www.example.com/b"}
    assert next(i for i in items if i.url.endswith("/a")).wire == "reuters"


def test_html_is_stripped():
    get = getter({"https://feed.example/rss": (FIX / "feed_html.xml").read_bytes()})
    (it,) = fetch.fetch_all([src()], NOW, get=get)
    assert it.title == "Hi"
    assert "<" not in it.title and "<" not in it.text
    assert "x()" not in it.title and "y()" not in it.text


def test_broken_feed_is_skipped():
    get = getter({
        "https://bad.example/rss": requests.Timeout("slow"),
        "https://feed.example/rss": (FIX / "feed_ok.xml").read_bytes(),
    })
    items = fetch.fetch_all([src("Bad", "https://bad.example/rss"), src("Good")], NOW, get=get)
    assert items and {i.source for i in items} == {"Good"}


def test_detect_wire():
    assert fetch.detect_wire("... (Reuters) - ...") == "reuters"
    assert fetch.detect_wire("MADRID, 3 nov (EFE).") == "efe"
    assert fetch.detect_wire("WASHINGTON (AP) — x") == "ap"
    assert fetch.detect_wire("Associated Press reported") == "ap"
    assert fetch.detect_wire("PARIS (AFP) -") == "afp"
    assert fetch.detect_wire("Buenos Aires (NA) - algo") == "noticias argentinas"
    assert fetch.detect_wire("Agencia NA") == "noticias argentinas"
    assert fetch.detect_wire("the NA region") is None
    assert fetch.detect_wire("plain text") is None


def test_one_item_per_topic():
    get = getter({"https://feed.example/rss": (FIX / "feed_ok.xml").read_bytes()})
    items = fetch.fetch_all([src(topics=("ai", "tech"))], NOW, get=get)
    assert len(items) == 4
    a = [i for i in items if i.url.endswith("/a")]
    assert {i.topic for i in a} == {"ai", "tech"}
    assert a[0].id != a[1].id and len(a[0].id) == 12


def test_short_summary_fetches_page_and_robots_disallow_skips():
    page = b"<html><body><article><p>" + b"Full article sentence number one. " * 40 + b"</p></article></body></html>"
    feed = (FIX / "feed_ok.xml").read_bytes()
    calls = []

    def get(url, **kw):
        calls.append(url)
        m = {"https://feed.example/rss": feed,
             "https://www.example.com/robots.txt": b"User-agent: *\nDisallow: /b\n",
             "https://www.example.com/a": page}
        if url not in m:
            return Resp(b"", 404)
        return Resp(m[url])
    items = fetch.fetch_all([src()], NOW, get=get)
    a = next(i for i in items if i.url.endswith("/a"))
    assert "Full article sentence" in a.text and len(a.text) <= 6000
    assert "https://www.example.com/b" not in calls  # robots disallow: page not fetched
    assert calls.count("https://www.example.com/robots.txt") == 1  # cached per host
    b = next(i for i in items if i.url.endswith("/b"))
    assert "Plain body" in b.text  # summary kept


def test_load_sources_valid():
    srcs = fetch.load_sources(Path(__file__).parent.parent / "sources.yaml")
    import config
    keys = {k for k, _ in config.TOPICS}
    for t in keys:
        assert 4 <= sum(t in s["topics"] for s in srcs) <= 8, t
    for s in srcs:
        assert set(s) >= {"name", "url", "topics", "kind", "reliability", "lang", "reason"}
        assert set(s["topics"]) <= keys and s["kind"] in ("primary", "wire", "outlet")
        assert s["lang"] in ("en", "es") and 0 <= s["reliability"] <= 1


def test_garbage_and_http_error_feeds_are_logged_and_skipped(caplog):
    get = getter({
        "https://junk.example/rss": b"<html>nope</html>",
        "https://feed.example/rss": (FIX / "feed_ok.xml").read_bytes(),
    })  # https://missing.example/rss is unmapped -> 404
    srcs = [src("Junk", "https://junk.example/rss"), src("Missing", "https://missing.example/rss"), src("Good")]
    with caplog.at_level("WARNING"):
        items = fetch.fetch_all(srcs, NOW, get=get)
    assert items and {i.source for i in items} == {"Good"}
    msgs = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("Junk" in m for m in msgs) and any("Missing" in m for m in msgs)


def test_dedupes_same_url_same_topic_across_sources():
    get = getter({"https://feed.example/rss": (FIX / "feed_ok.xml").read_bytes(),
                  "https://feed2.example/rss": (FIX / "feed_ok.xml").read_bytes()})
    items = fetch.fetch_all([src("First"), src("Second", "https://feed2.example/rss")], NOW, get=get)
    assert len(items) == 2 and len({i.id for i in items}) == 2
    assert {i.source for i in items} == {"First"}
