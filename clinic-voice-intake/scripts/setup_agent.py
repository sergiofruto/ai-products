"""Create or update the ElevenLabs agent and its client tools from code.

The agent's whole configuration lives here (prompt, voice, tools), so it is
reviewed and versioned like any other code instead of living only in a dashboard.

Usage:  .venv/bin/python scripts/setup_agent.py
Reads ELEVENLABS_API_KEY from .env, keeps created ids in scripts/agent_ids.json,
and writes NEXT_PUBLIC_ELEVENLABS_AGENT_ID to .env.local for the web app.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDS_FILE = ROOT / "scripts" / "agent_ids.json"
API = "https://api.elevenlabs.io"

ALLOWED_HOSTS = ["pt-intake-agent.vercel.app", "localhost"]
AGENT_NAME = "Movimiento PT - intake (demo)"
LLM = os.environ.get("AGENT_LLM", "claude-sonnet-4-5")
VOICE_ID = os.environ.get("AGENT_VOICE_ID", "")  # empty = ElevenLabs default voice

PROMPT = """\
You are the front desk of "Movimiento", a physical therapy clinic in Buenos Aires.
You do patient intake by voice and book a first evaluation. Speak the patient's
language (Spanish or English). Keep every turn short: one question at a time.

Collect, in this order:
1. Full name.
2. Reason for the visit: which body area and since when. Map the area to one of:
   neck, upper_back, lower_back, shoulder, elbow, wrist_hand, hip, knee, ankle_foot, other.
3. Pain level from 0 (no pain) to 10 (worst imaginable). Ask for a single number.
4. Preferred day and morning/afternoon. Then call check_availability and offer
   at most two of the returned slots, reading their labels.

After each answer, call record_intake with the fields you know so far.

Before booking, read back name, area, pain level and the chosen slot and ask the
patient to confirm. Only then call book_appointment with the exact slot_id.
- If it returns ok=false, explain the problem in plain words, fix it with the
  patient, and try again. Never say an appointment is booked unless the tool
  returned ok=true.
- If it returns ok=true, give the confirmation code, letter by letter, and say goodbye.

Rules: you are not a clinician. Never diagnose or give treatment advice; if asked,
say the physical therapist will cover it in the evaluation. Never invent slots,
dates or codes; they only come from the tools. Pass lang="es" to tools when
speaking Spanish, otherwise "en".
"""

FIRST_MESSAGE = (
    "Hi, this is Movimiento physical therapy. I can book your first evaluation. "
    "You can speak English or Spanish. What's your full name?"
)
FIRST_MESSAGE_ES = (
    "Hola, te habla Movimiento, centro de kinesiología. Te ayudo a reservar tu "
    "primera evaluación. ¿Cuál es tu nombre completo?"
)

TOOLS = [
    {
        "type": "client",
        "name": "record_intake",
        "description": "Show the intake fields collected so far on the clinic screen. "
                       "Call after each new answer. Send only fields you know.",
        "expects_response": False,
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "Full name"},
                "body_area": {"type": "string", "description": "One of the allowed body areas"},
                "reason": {"type": "string", "description": "Short reason, e.g. 'knee pain after running, 2 weeks'"},
                "pain_level": {"type": "integer", "description": "0 to 10"},
            },
            "required": [],
        },
    },
    {
        "type": "client",
        "name": "check_availability",
        "description": "Get free appointment slots. Returns today's date, up to 3 slots "
                       "(slot_id + label to read aloud) and a note if the preferred date was full.",
        "expects_response": True,
        "parameters": {
            "type": "object",
            "properties": {
                "preferred_date": {"type": "string", "description": "YYYY-MM-DD, if the patient named a day"},
                "part_of_day": {"type": "string", "description": "morning, afternoon or any"},
                "lang": {"type": "string", "description": "en or es"},
            },
            "required": ["part_of_day", "lang"],
        },
    },
    {
        "type": "client",
        "name": "book_appointment",
        "description": "Book the confirmed slot. The clinic system validates every field "
                       "and returns ok=true with a confirmation code, or ok=false with errors to fix.",
        "expects_response": True,
        "parameters": {
            "type": "object",
            "properties": {
                "patient_name": {"type": "string", "description": "Full name"},
                "body_area": {"type": "string", "description": "One of the allowed body areas"},
                "reason": {"type": "string", "description": "Short reason for the visit"},
                "pain_level": {"type": "integer", "description": "0 to 10"},
                "slot_id": {"type": "string", "description": "Exact slot_id from check_availability"},
                "lang": {"type": "string", "description": "en or es"},
            },
            "required": ["patient_name", "body_area", "reason", "pain_level", "slot_id", "lang"],
        },
    },
]


def load_key() -> str:
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("ELEVENLABS_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit("ELEVENLABS_API_KEY missing from .env")


def call(method: str, path: str, key: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"xi-api-key": key, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}\n{e.read().decode()[:2000]}")


def agent_body(tool_ids: list[str]) -> dict:
    # English agents must use a v2 model; ElevenLabs switches to v2.5 multilingual for other languages.
    tts = {"model_id": "eleven_flash_v2"}
    if VOICE_ID:
        tts["voice_id"] = VOICE_ID
    return {
        "name": AGENT_NAME,
        "tags": ["demo", "physical-therapy"],
        "conversation_config": {
            "agent": {
                "first_message": FIRST_MESSAGE,
                "language": "en",
                "prompt": {
                    "prompt": PROMPT, "llm": LLM, "tool_ids": tool_ids,
                    "built_in_tools": {
                        "language_detection": {
                            "type": "system", "name": "language_detection", "description": "",
                            "params": {"system_tool_type": "language_detection"},
                        },
                        "end_call": {
                            "type": "system", "name": "end_call", "description": "",
                            "params": {"system_tool_type": "end_call"},
                        },
                    },
                },
            },
            "language_presets": {
                "es": {"overrides": {"agent": {"first_message": FIRST_MESSAGE_ES, "language": "es"}}},
            },
            "tts": tts,
            "conversation": {"max_duration_seconds": 300},
        },
        # Public agent (no signed URL) so anyone can try the demo, but only from
        # these sites, so others can't embed it and spend the account's credits.
        "platform_settings": {
            "auth": {"allowlist": [{"hostname": h} for h in ALLOWED_HOSTS]},
        },
    }


def main() -> None:
    key = load_key()
    ids = json.loads(IDS_FILE.read_text()) if IDS_FILE.exists() else {"tools": {}}

    for tool in TOOLS:
        existing = ids["tools"].get(tool["name"])
        if existing:
            call("PATCH", f"/v1/convai/tools/{existing}", key, {"tool_config": tool})
            print(f"updated tool {tool['name']}")
        else:
            res = call("POST", "/v1/convai/tools", key, {"tool_config": tool})
            ids["tools"][tool["name"]] = res["id"]
            print(f"created tool {tool['name']} -> {res['id']}")
            IDS_FILE.write_text(json.dumps(ids, indent=2) + "\n")  # keep ids even if a later step fails

    body = agent_body(list(ids["tools"].values()))
    if ids.get("agent_id"):
        call("PATCH", f"/v1/convai/agents/{ids['agent_id']}", key, body)
        print(f"updated agent {ids['agent_id']}")
    else:
        res = call("POST", "/v1/convai/agents/create", key, body)
        ids["agent_id"] = res["agent_id"]
        print(f"created agent {ids['agent_id']}")

    IDS_FILE.write_text(json.dumps(ids, indent=2) + "\n")
    (ROOT / ".env.local").write_text(f"NEXT_PUBLIC_ELEVENLABS_AGENT_ID={ids['agent_id']}\n")
    print("wrote .env.local")


if __name__ == "__main__":
    main()
