"""HTTP layer for the clinic rules. Deployed as a Vercel Python function;
locally run with: .venv/bin/uvicorn api.index:app --port 8000"""
from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import FastAPI
from pydantic import BaseModel, Field

try:  # Vercel imports this file as a module inside api/
    from . import _clinic as clinic
except ImportError:  # pragma: no cover
    import _clinic as clinic  # type: ignore

app = FastAPI(docs_url="/api/py/docs", openapi_url="/api/py/openapi.json")


class AvailabilityIn(BaseModel):
    preferred_date: date | None = None
    part_of_day: clinic.PartOfDay = "any"
    lang: str = Field(default="en", pattern="^(en|es)$")


class BookingIn(BaseModel):
    # Loose types on purpose: the rules in clinic.book() decide what's valid
    # and explain it, instead of a generic 422 the agent can't act on.
    patient_name: str = ""
    body_area: str = ""
    reason: str = ""
    pain_level: int | float | str | None = None
    slot_id: str = ""
    lang: str = "en"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/api/py/health")
def health() -> dict:
    return {"ok": True}


@app.post("/api/py/availability")
def availability(body: AvailabilityIn) -> dict:
    return clinic.find_availability(_now(), body.preferred_date, body.part_of_day, body.lang)


@app.post("/api/py/book")
def book(body: BookingIn) -> dict:
    pain = body.pain_level
    if isinstance(pain, str) and pain.strip().isdigit():
        pain = int(pain.strip())
    if isinstance(pain, float) and pain.is_integer():
        pain = int(pain)
    return clinic.book(
        _now(),
        patient_name=body.patient_name,
        body_area=body.body_area,
        reason=body.reason,
        pain_level=pain,  # type: ignore[arg-type]
        slot_id=body.slot_id,
        lang=body.lang if body.lang in ("en", "es") else "en",
    )
