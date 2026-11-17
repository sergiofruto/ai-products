"""All settings, loaded from .env via python-dotenv. Key values are never logged."""
import os
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")

DB_PATH = os.getenv("DB_PATH", str(HERE / "news.db"))
EXPORT_DIR = os.getenv("EXPORT_DIR", str(HERE / "exports"))

# Web server: reachable from this Mac only
WEB_HOST = "127.0.0.1"
WEB_PORT = int(os.getenv("WEB_PORT", "5008"))

# API keys: a missing key means that model is skipped
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

# Budget: the pipeline run may spend up to cap - reserve; projections may spend up to the full cap
AI_DAILY_CAP_USD = float(os.getenv("AI_DAILY_CAP_USD", "1.50"))
AI_PROJECTION_RESERVE_USD = float(os.getenv("AI_PROJECTION_RESERVE_USD", "0.25"))

# Columns, in order: (id, display name)
TOPICS: list[tuple[str, str]] = [
    ("ai", "AI"),
    ("tech", "Tech"),
    ("stocks", "Stocks"),
    ("world", "World"),
    ("argentina", "Argentina"),
]
STORIES_PER_TOPIC = 5
CLUSTER_WINDOW_HOURS = 24
CLAIMS_MIN, CLAIMS_MAX = 3, 6
SOURCE_TEXT_CHARS = 1500

# Score weights and bands (spec)
SOURCE_COUNT_POINTS = {1: 5, 2: 15, 3: 22}  # 4+ -> SOURCE_COUNT_MAX
SOURCE_COUNT_MAX = 30
PRIMARY_SOURCE_POINTS = 20
AGREEMENT_POINTS = 30
AGREEMENT_CAP_BY_MODELS = {3: 30, 2: 24, 1: 15}
AGREEMENT_PENALTY_PER_REFUTED = 5
RELIABILITY_WEIGHT = 15
FRESHNESS_POINTS = 5
BAND_HIGH, BAND_MEDIUM = 80, 60

# Models
WRITER_MODEL = "claude-sonnet-5-5"
CLUSTER_MODEL = "claude-haiku-5-5"
# Validator models for OpenAI / xAI are placeholders read from env.
VALIDATORS: list[tuple[str, str]] = [
    ("anthropic", "claude-haiku-5-5"),
    ("openai", os.getenv("OPENAI_VALIDATOR_MODEL", "gpt-5-mini")),
    ("xai", os.getenv("XAI_VALIDATOR_MODEL", "grok-4-fast")),
]

# USD per million (input, output) tokens. Claude prices: claude-api skill model table, cached 2026-10-06.
# Haiku's price holds for prompts up to 100K tokens (beyond that: $0.50 in / $2.50 out); our prompts stay well below.
# The OpenAI and xAI validator models are deliberately NOT listed: their prices are unverified, so
# budget.cost_usd prices them like the most expensive known model rather than as free.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
