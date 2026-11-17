from datetime import date, timedelta

import config
from budget import Budget, cost_usd

D = date(2026, 11, 17)


def _spend(b, day, usd):
    # claude-sonnet-5-5 input is $2.00 per 1M tokens
    b.record("run", "anthropic", "claude-sonnet-5-5", int(usd / 2.00 * 1_000_000), 0, day)


def test_run_stops_before_reserve(conn):
    b = Budget(conn, 1.50, 0.25)
    _spend(b, D, 1.25)
    assert not b.can_spend("run", D)
    assert b.can_spend("projection", D)


def test_projection_stops_at_cap(conn):
    b = Budget(conn, 1.50, 0.25)
    _spend(b, D, 1.50)
    assert not b.can_spend("projection", D)


def test_unknown_model_priced_as_most_expensive():
    assert cost_usd("mystery", 1_000_000, 0) == max(p[0] for p in config.MODEL_PRICES.values())


def test_spend_is_per_day(conn):
    b = Budget(conn, 1.50, 0.25)
    _spend(b, D - timedelta(days=1), 1.50)
    assert b.can_spend("run", D)
    assert b.spent_today(D) == 0
