from datetime import datetime, timedelta, timezone

import pytest

import rules
from models import Item

T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def mk(id, host, *, kind="outlet", wire=None, text="", lang="en", minutes=0, rel=0.5):
    return Item(id=id, topic="ai", source=host, kind=kind, url=f"https://{host}/{id}", host=host,
                title=id, published=T0 + timedelta(minutes=minutes), text=text, lang=lang,
                reliability=rel, wire=wire)


def test_sources_points():
    pts = [rules.score(independent=n, has_primary=False, verdicts=[], models_answered=3,
                       avg_reliability=0, corrected=False)["sources"] for n in (0, 1, 2, 3, 4, 7)]
    assert pts == [0, 5, 15, 22, 30, 30]


def test_combine_three():
    s, c, n = "supported", "contradicted", "not_found"
    assert rules.combine_votes([s, s, s]) == "agreed"
    assert rules.combine_votes([s, s, n]) == "agreed"
    assert rules.combine_votes([s, s, c]) == "disputed"
    assert rules.combine_votes([s, n, n]) == "disputed"
    assert rules.combine_votes([n, n, n]) == "unverified"
    assert rules.combine_votes([c, c, s]) == "unverified"


def test_combine_two_and_one():
    s, c, n = "supported", "contradicted", "not_found"
    assert rules.combine_votes([s, s]) == "agreed"
    assert rules.combine_votes([s, n]) == "disputed"
    assert rules.combine_votes([n, n]) == "unverified"
    assert rules.combine_votes([s, c]) == "disputed"
    assert rules.combine_votes([s]) == "agreed"
    assert rules.combine_votes([c]) == "unverified"


def _agr(verdicts, models):
    return rules.score(independent=0, has_primary=False, verdicts=verdicts, models_answered=models,
                       avg_reliability=0, corrected=False)["agreement"]


def test_agreement_cap_by_models():
    v = ["agreed"] * 4
    assert (_agr(v, 3), _agr(v, 2), _agr(v, 1)) == (30, 24, 15)


def test_agreement_penalty_floor():
    assert _agr(["agreed"] + ["unverified"] * 3, 3) == 0


def test_agreement_no_claims():
    assert _agr([], 3) == 0


def test_full_example():
    r = rules.score(independent=3, has_primary=True, verdicts=["agreed"] * 4, models_answered=3,
                    avg_reliability=0.8, corrected=False)
    assert r == {"sources": 22, "primary": 20, "agreement": 30, "reliability": 12,
                 "freshness": 5, "total": 89, "band": "high"}


def test_corrected_loses_freshness():
    r = rules.score(independent=0, has_primary=False, verdicts=[], models_answered=3,
                    avg_reliability=0, corrected=True)
    assert r["freshness"] == 0


def test_bands():
    def band(total):
        # sources 30 + primary 20 + freshness 5 = 55; tune reliability to hit the total
        return rules.band_for(total)
    assert [band(80), band(79), band(60), band(59)] == ["high", "medium", "medium", "low"]


def test_wire_copies_count_once():
    items = [mk("a", "h1", wire="reuters", text="aaa"), mk("b", "h2", wire="reuters", text="bbb"),
             mk("c", "h3", wire="reuters", text="ccc"), mk("d", "h4", text="own reporting xyz")]
    assert rules.independent_count(items) == 2


def test_near_identical_text_counts_once():
    t = "The company announced a new model today with major improvements. " * 5
    assert rules.independent_count([mk("a", "h1", text=t), mk("b", "h2", text=t)]) == 1


def test_different_text_counts_separately():
    assert rules.independent_count([mk("a", "h1", text="alpha beta " * 30),
                                    mk("b", "h2", text="zzz qqq www " * 30)]) == 2


def test_top_sources_order_and_no_repeat_host():
    items = [
        mk("o1", "outlet.com", minutes=5, text="x" * 10, rel=0.9),
        mk("p1", "gov.org", kind="primary", minutes=10, text="y" * 20, rel=0.7),
        mk("o2", "early.com", minutes=0, text="z" * 5, rel=0.6),
        mk("o3", "long.com", minutes=3, text="w" * 500, rel=0.5),
        mk("o4", "outlet.com", minutes=1, text="v" * 900, rel=0.95),
    ]
    out = rules.top_sources(items)
    assert [o["item_id"] for o in out] == ["p1", "o2", "o4"]
    assert out[0]["reason"] == "Primary source: published the original"
    assert out[1]["reason"] == "First to report"
    assert out[2]["reason"] == "Most detail"
    assert {"item_id", "source", "url", "reason"} == set(out[0])
    assert len({o["item_id"] for o in out}) == 3


def test_top_sources_fills_with_reliable_and_skips_dup_hosts():
    items = [mk("a", "h1", minutes=0, text="aa", rel=0.2), mk("b", "h2", minutes=5, text="bbbb", rel=0.9),
             mk("c", "h3", minutes=6, text="b", rel=0.95)]
    out = rules.top_sources(items)
    assert [o["item_id"] for o in out] == ["a", "b", "c"]
    assert out[2]["reason"] == "Most reliable outlet"
    assert len(rules.top_sources([mk("a", "h", text="x"), mk("b", "h", text="yy")])) == 1
