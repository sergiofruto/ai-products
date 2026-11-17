from datetime import datetime, timezone

import validate
from models import Item
from tests.fakes import FakeLLM

T0 = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def mk(id, text="body"):
    return Item(id=id, topic="ai", source="Src", kind="outlet", url=f"https://x.com/{id}", host="x.com",
                title="t", published=T0, text=text, lang="en", reliability=0.5)


CLAIMS = [{"en": "c1", "es": "c1 es"}, {"en": "c2", "es": "c2 es"}]
ITEMS = [mk("a"), mk("b")]


def v(*votes, **kw):
    return FakeLLM([{"votes": list(votes)}], **kw)


def test_three_models_majority():
    vs = [v("supported", "supported", provider="p1"),
          v("supported", "contradicted", provider="p2"),
          v("supported", "not_found", provider="p3")]
    verdicts, votes = validate.check(vs, CLAIMS, ITEMS)
    assert verdicts == ["agreed", "disputed"]
    assert votes["p3"] == ["supported", "not_found"]
    assert set(votes) == {"p1", "p2", "p3"}


def test_bad_length_reply_ignored():
    vs = [v("supported", provider="p1"), v("supported", "supported", provider="p2")]
    _, votes = validate.check(vs, CLAIMS, ITEMS)
    assert "p1" not in votes and "p2" in votes


def test_invalid_vote_value_ignored():
    vs = [v("supported", "maybe", provider="p1"), v("supported", "supported", provider="p2")]
    _, votes = validate.check(vs, CLAIMS, ITEMS)
    assert "p1" not in votes and "p2" in votes


def test_no_model_answers_all_unverified():
    vs = [FakeLLM([None], provider="p1"), FakeLLM([], provider="p2")]
    verdicts, votes = validate.check(vs, CLAIMS, ITEMS)
    assert verdicts == ["unverified", "unverified"]
    assert votes == {}


def test_unavailable_skipped():
    m = v("supported", "supported", provider="p1")
    m.available = False
    verdicts, votes = validate.check([m], CLAIMS, ITEMS)
    assert m.calls == [] and votes == {} and verdicts == ["unverified"] * 2


def test_source_text_trimmed_to_1500():
    m = v("supported", "supported")
    validate.check([m], CLAIMS, [mk("a", "x" * 3000)])
    user = m.calls[0]["user"]
    assert "x" * 1500 in user and "x" * 1501 not in user
    assert "1. c1" in user and "2. c2" in user and "c1 es" not in user
