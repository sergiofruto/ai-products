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
