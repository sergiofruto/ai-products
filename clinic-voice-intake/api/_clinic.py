"""Clinic rules for the intake agent.

The voice agent never decides anything here. It collects answers and calls
these functions through the API; plain code checks the data and owns the
schedule. Every function is pure (the clock is passed in) so it is easy to test.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

CLINIC_TZ = ZoneInfo("America/Argentina/Buenos_Aires")
OPEN_HOURS = [9, 10, 11, 12, 14, 15, 16, 17]  # 13:00 is lunch
DAYS_AHEAD = 10
SESSION_MINUTES = 45

BODY_AREAS = (
    "neck", "upper_back", "lower_back", "shoulder", "elbow", "wrist_hand",
    "hip", "knee", "ankle_foot", "other",
)
PartOfDay = Literal["morning", "afternoon", "any"]


def _slot_id(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M")


def _is_taken(dt: datetime) -> bool:
    # Deterministic "already booked" slots so the calendar looks real and the
    # same slot is busy on every server instance (no database in the demo).
    digest = hashlib.sha256(_slot_id(dt).encode()).digest()
    return digest[0] % 3 == 0


def _label(dt: datetime, lang: str) -> str:
    days_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days_es = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    months_en = ["January", "February", "March", "April", "May", "June", "July",
                 "August", "September", "October", "November", "December"]
    months_es = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
                 "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    if lang == "es":
        return f"{days_es[dt.weekday()]} {dt.day} de {months_es[dt.month - 1]}, {dt:%H:%M}"
    return f"{days_en[dt.weekday()]}, {months_en[dt.month - 1]} {dt.day} at {dt:%H:%M}"


def all_slots(now: datetime) -> list[datetime]:
    """Weekday slots from tomorrow up to DAYS_AHEAD days out, in clinic time."""
    now = now.astimezone(CLINIC_TZ)
    slots = []
    for offset in range(1, DAYS_AHEAD + 1):
        day = now.date() + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        for hour in OPEN_HOURS:
            slots.append(datetime.combine(day, time(hour), CLINIC_TZ))
    return slots


def find_availability(
    now: datetime,
    preferred_date: date | None = None,
    part_of_day: PartOfDay = "any",
    lang: str = "en",
    limit: int = 3,
) -> dict:
    """Up to `limit` free slots. If the preferred date has nothing, say so and
    offer the nearest alternatives instead of returning an empty list."""
    free = [s for s in all_slots(now) if not _is_taken(s)]
    if part_of_day == "morning":
        free = [s for s in free if s.hour < 13]
    elif part_of_day == "afternoon":
        free = [s for s in free if s.hour >= 13]

    note = None
    matches = free
    if preferred_date is not None:
        on_day = [s for s in free if s.date() == preferred_date]
        if on_day:
            matches = on_day
        else:
            note = "no_slots_on_preferred_date"
            matches = sorted(free, key=lambda s: (abs((s.date() - preferred_date).days), s))

    return {
        "today": now.astimezone(CLINIC_TZ).date().isoformat(),
        "note": note,
        "slots": [{"slot_id": _slot_id(s), "label": _label(s, lang)} for s in matches[:limit]],
    }


def book(
    now: datetime,
    *,
    patient_name: str,
    body_area: str,
    reason: str,
    pain_level: int,
    slot_id: str,
    lang: str = "en",
) -> dict:
    """Validate the intake and book the slot. Returns every problem at once so
    the agent can fix them in one turn, never a partial booking."""
    errors: list[dict] = []

    name = " ".join(patient_name.split())
    if len(name) < 2 or len(name) > 80:
        errors.append({"field": "patient_name", "problem": "missing_or_invalid"})

    if body_area not in BODY_AREAS:
        errors.append({"field": "body_area", "problem": f"must be one of {', '.join(BODY_AREAS)}"})

    if len(reason.strip()) < 3:
        errors.append({"field": "reason", "problem": "missing"})

    if not isinstance(pain_level, int) or isinstance(pain_level, bool) or not 0 <= pain_level <= 10:
        errors.append({"field": "pain_level", "problem": "must be a whole number from 0 to 10"})

    slot = None
    try:
        slot = datetime.strptime(slot_id, "%Y-%m-%dT%H:%M").replace(tzinfo=CLINIC_TZ)
    except ValueError:
        errors.append({"field": "slot_id", "problem": "unknown_slot"})
    if slot is not None:
        if slot not in all_slots(now):
            errors.append({"field": "slot_id", "problem": "outside_clinic_hours_or_dates"})
        elif _is_taken(slot):
            errors.append({"field": "slot_id", "problem": "already_taken"})

    if errors:
        return {"ok": False, "errors": errors}

    code = "PT-" + hashlib.sha256(f"{name}|{slot_id}".encode()).hexdigest()[:6].upper()
    return {
        "ok": True,
        "confirmation_code": code,
        "appointment": {
            "patient_name": name,
            "body_area": body_area,
            "reason": reason.strip(),
            "pain_level": pain_level,
            "slot_id": slot_id,
            "label": _label(slot, lang),
            "duration_minutes": SESSION_MINUTES,
        },
    }
