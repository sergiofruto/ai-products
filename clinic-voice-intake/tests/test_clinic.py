from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from api import _clinic as clinic
from api.index import app

# Tuesday 2026-11-10, 15:00 UTC (12:00 in Buenos Aires)
NOW = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


def free_slot_id(now=NOW, **kw):
    return clinic.find_availability(now, **kw)["slots"][0]["slot_id"]


def taken_slot_id(now=NOW):
    for s in clinic.all_slots(now):
        if clinic._is_taken(s):
            return clinic._slot_id(s)
    raise AssertionError("expected at least one taken slot")


def valid_booking(**overrides):
    data = dict(patient_name="Ana Gómez", body_area="knee",
                reason="pain after running for two weeks", pain_level=6,
                slot_id=free_slot_id())
    data.update(overrides)
    return data


# ── availability ────────────────────────────────────────────────────────────

def test_slots_start_tomorrow_skip_weekends_and_lunch():
    slots = clinic.all_slots(NOW)
    assert min(s.date() for s in slots) == date(2026, 11, 11)
    assert all(s.weekday() < 5 for s in slots)
    assert all(s.hour != 13 for s in slots)


def test_availability_returns_only_free_slots():
    result = clinic.find_availability(NOW, limit=50)
    taken = {clinic._slot_id(s) for s in clinic.all_slots(NOW) if clinic._is_taken(s)}
    assert taken, "the demo calendar should have some busy slots"
    assert not taken & {s["slot_id"] for s in result["slots"]}
    assert result["today"] == "2026-11-10"


def test_part_of_day_filter():
    morning = clinic.find_availability(NOW, part_of_day="morning", limit=50)["slots"]
    afternoon = clinic.find_availability(NOW, part_of_day="afternoon", limit=50)["slots"]
    assert all(int(s["slot_id"][11:13]) < 13 for s in morning)
    assert all(int(s["slot_id"][11:13]) >= 13 for s in afternoon)


def test_weekend_request_offers_nearest_alternatives():
    result = clinic.find_availability(NOW, preferred_date=date(2026, 11, 14))  # Saturday
    assert result["note"] == "no_slots_on_preferred_date"
    assert len(result["slots"]) == 3


def test_spanish_labels():
    label = clinic.find_availability(NOW, lang="es")["slots"][0]["label"]
    assert "de noviembre" in label


# ── booking ─────────────────────────────────────────────────────────────────

def test_valid_booking_is_confirmed():
    result = clinic.book(NOW, **valid_booking())
    assert result["ok"] is True
    assert result["confirmation_code"].startswith("PT-")
    assert result["appointment"]["pain_level"] == 6


def test_pain_level_out_of_range_is_rejected():
    result = clinic.book(NOW, **valid_booking(pain_level=12))
    assert result == {"ok": False, "errors": [
        {"field": "pain_level", "problem": "must be a whole number from 0 to 10"}]}


def test_taken_slot_is_rejected():
    result = clinic.book(NOW, **valid_booking(slot_id=taken_slot_id()))
    assert {"field": "slot_id", "problem": "already_taken"} in result["errors"]


def test_slot_outside_hours_is_rejected():
    result = clinic.book(NOW, **valid_booking(slot_id="2026-11-11T13:00"))
    assert result["errors"][0]["problem"] == "outside_clinic_hours_or_dates"


def test_all_problems_are_reported_together():
    result = clinic.book(NOW, patient_name="", body_area="heart", reason="",
                         pain_level=-1, slot_id="tomorrow")
    assert {e["field"] for e in result["errors"]} == {
        "patient_name", "body_area", "reason", "pain_level", "slot_id"}


# ── HTTP layer ──────────────────────────────────────────────────────────────

def test_api_accepts_pain_as_text_digit():
    client = TestClient(app)
    slot = client.post("/api/py/availability", json={}).json()["slots"][0]["slot_id"]
    body = valid_booking(pain_level="7", slot_id=slot)
    assert client.post("/api/py/book", json=body).json()["ok"] is True


def test_api_reports_bad_fields_instead_of_422():
    client = TestClient(app)
    res = client.post("/api/py/book", json={"pain_level": "a lot"})
    assert res.status_code == 200
    assert res.json()["ok"] is False
