# Clinic Voice Intake (ElevenAgents demo)

A bilingual (English/Spanish) voice agent that does intake for a physical therapy
clinic and books a first evaluation. Built on **ElevenAgents**, with a **Python
(FastAPI)** clinic API and a **Next.js** page that shows what happens behind the voice.

## The flow

1. Name
2. Reason for the visit: body area and since when
3. Pain level, 0 to 10
4. Preferred day and morning/afternoon → `check_availability` → the agent offers real slots
5. Read-back and confirmation → `book_appointment` → confirmation code

## Design decisions

- **The model talks, code decides.** The agent never invents slots, dates or codes.
  They only come from the clinic API (`api/_clinic.py`), which owns the schedule and
  validates every field.
- **Errors are part of the conversation.** A rejected booking returns *all* problems
  at once (`{"ok": false, "errors": [...]}`) instead of a generic HTTP 422, so the
  agent can fix them with the patient in one turn. The prompt forbids saying
  "booked" unless the tool returned `ok: true`.
- **Client tools, visible by design.** The agent's tools run in the browser and call
  the Python API, so every call, its parameters, result and latency appear in the
  "Behind the voice" panel.
- **Agent config as code.** Prompt, voice, languages and tools live in
  `scripts/setup_agent.py` and are applied through the ElevenLabs API, so changes are
  reviewed and versioned like code instead of living only in a dashboard.
- **Pure, tested rules.** The clinic logic takes the clock as a parameter, so it's
  deterministic and fully unit tested (`tests/`).
- **Scope guardrail.** The agent is front desk, not a clinician: no diagnosis or
  treatment advice.

## Limits (on purpose for v1)

- Demo data: a fictional clinic and a generated calendar. Busy slots are
  deterministic, and bookings are not persisted (no database), so two visitors can
  book the same slot.
- No red-flag triage, insurance, rescheduling or authentication yet.
- The agent is public (no signed URL) so anyone can try it. A real deployment would
  use signed URLs from a backend and a domain allowlist.

## Run it locally

```bash
python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn pytest httpx
echo "ELEVENLABS_API_KEY=sk_..." > .env          # never commit this
.venv/bin/python scripts/setup_agent.py          # creates tools + agent, writes .env.local
npm install
.venv/bin/uvicorn api.index:app --port 8000 &    # clinic API
npm run dev                                       # http://localhost:3000
```

Tests: `.venv/bin/python -m pytest -q`

## Stack

ElevenAgents (`@elevenlabs/react`, client tools, language presets) · Python 3 ·
FastAPI · Next.js 16 · React 19 · Tailwind CSS 4 · Vercel
