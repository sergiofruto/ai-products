from datetime import datetime, timedelta, timezone

import cluster
from models import Item
from tests.fakes import FakeLLM

T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def mk(id, host, minutes=0, text=None):
    return Item(id=id, topic="ai", source=host, kind="outlet", url=f"https://{host}/{id}", host=host,
                title=f"title {id}", published=T0 + timedelta(minutes=minutes), text=text or {"a":"Alpha chip launch.","b":"Quarterly revenue beat estimates.","c":"Regulators open probe into merger."}.get(id, id), lang="en",
                reliability=0.5)


def ids(groups):
    return [[i.id for i in g] for g in groups]


def test_groups_follow_model():
    items = [mk("a", "x.com"), mk("b", "y.com"), mk("c", "z.com")]
    llm = FakeLLM([{"stories": [[1, 3], [2]]}])
    groups = cluster.cluster(llm, "ai", items)
    assert sorted(ids(groups)) == [["a", "c"], ["b"]]
    assert "[1] title a" in llm.calls[0]["user"]
    assert llm.calls[0]["job"] == "run"


def test_unknown_and_duplicate_ids_ignored():
    items = [mk("a", "x.com"), mk("b", "y.com")]
    llm = FakeLLM([{"stories": [[1, 9, "x", 0, 1], [1, 2]]}])
    groups = cluster.cluster(llm, "ai", items)
    assert sorted(ids(groups)) == [["a"], ["b"]]


def test_unassigned_become_singletons():
    items = [mk("a", "x.com"), mk("b", "y.com"), mk("c", "z.com")]
    groups = cluster.cluster(FakeLLM([{"stories": [[1, 2]]}]), "ai", items)
    assert sorted(ids(groups)) == [["a", "b"], ["c"]]


def test_model_failure_falls_back_to_singletons():
    items = [mk("a", "x.com"), mk("b", "y.com")]
    groups = cluster.cluster(FakeLLM([RuntimeError("x")]), "ai", items)
    assert sorted(ids(groups)) == [["a"], ["b"]]


def test_sorted_by_independent_sources():
    items = [mk("a", "x.com", 50), mk("b", "y.com", 0), mk("c", "z.com", 1)]
    groups = cluster.cluster(FakeLLM([{"stories": [[2, 3], [1]]}]), "ai", items)
    assert ids(groups) == [["b", "c"], ["a"]]


def mt(id, topic, host, url=None):
    return Item(id=id, topic=topic, source=host, kind="outlet", url=url or f"https://{host}/{id}", host=host,
                title=f"title {id}", published=T0, text={"t1": "Chip maker names new chief.", "t2": "Markets rally after board vote.", "a1": "AI leader returns to the company."}.get(id, "text " + id), lang="en", reliability=0.5)


def test_merge_across_joins_same_event_into_best_sourced_topic():
    nv_ai = [mt("a1", "ai", "x.com")]
    nv_tech = [mt("t1", "tech", "y.com"), mt("t2", "tech", "z.com")]
    other = [mt("t3", "tech", "w.com")]
    llm = FakeLLM([{"same": [[1, 2]]}])
    out = cluster.merge_across(llm, [("ai", nv_ai), ("tech", nv_tech), ("tech", other)])
    assert [(t, [i.id for i in g]) for t, g in out] == [("tech", ["t1", "t2", "a1"]), ("tech", ["t3"])]
    assert "[1] (ai) title a1" in llm.calls[0]["user"] and llm.calls[0]["job"] == "run"


def test_merge_across_tie_keeps_earlier_candidate_and_dedupes_urls():
    a = [mt("a1", "ai", "x.com", url="https://x.com/same")]
    t = [mt("t1", "tech", "x.com", url="https://x.com/same")]
    out = cluster.merge_across(FakeLLM([{"same": [[2, 1]]}]), [("ai", a), ("tech", t)])
    assert [(tp, [i.id for i in g]) for tp, g in out] == [("ai", ["a1"])]


def test_merge_across_ignores_bad_numbers_and_reuse():
    c = [("ai", [mt("a1", "ai", "x.com")]), ("tech", [mt("t1", "tech", "y.com")]), ("world", [mt("w1", "world", "z.com")])]
    out = cluster.merge_across(FakeLLM([{"same": [[1, 9, "2", True], [1, 3], [2]]}]), c)
    assert [(tp, [i.id for i in g]) for tp, g in out] == [("ai", ["a1", "w1"]), ("tech", ["t1"])]


def test_merge_across_model_failure_or_single_candidate_is_unchanged():
    c = [("ai", [mt("a1", "ai", "x.com")]), ("tech", [mt("t1", "tech", "y.com")])]
    assert cluster.merge_across(FakeLLM([RuntimeError("x")]), c) == c
    llm = FakeLLM([])
    assert cluster.merge_across(llm, c[:1]) == c[:1] and llm.calls == []
