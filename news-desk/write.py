"""Bilingual story writer with citation checks done in code."""
from dataclasses import dataclass

import config
from models import Item

SYSTEM = f"""You are a news writer. Write each story in English and Spanish.
Keep verbatim quotes in their original language, with attribution.
Every summary paragraph lists the item ids it relies on.
Claims are {config.CLAIMS_MIN}-{config.CLAIMS_MAX} specific, checkable factual statements taken from the sources.
Never recommend buying, selling or holding any security and never give price targets.
Use only the given sources; do not add outside facts.
Reply with JSON only, in this shape:
{{"headline": {{"en": "...", "es": "..."}}, "oneliner": {{"en": "...", "es": "..."}},
"summary": [{{"en": "...", "es": "...", "sources": ["<item id>", ...]}}],
"claims": [{{"en": "...", "es": "..."}}]}}"""


@dataclass
class Draft:
    headline: dict
    oneliner: dict
    summary: list[dict]
    claims: list[dict]


def _bi(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    en, es = v.get("en"), v.get("es")
    if not (isinstance(en, str) and en.strip() and isinstance(es, str) and es.strip()):
        return None
    return {"en": en, "es": es}


def write_story(llm, items: list[Item]) -> Draft | None:
    user = "Sources:\n" + "\n".join(
        f"{i.id}: {i.source} — {i.title} — {i.text[:config.SOURCE_TEXT_CHARS]}" for i in items)
    data = llm.ask_json("run", SYSTEM, user, max_tokens=8000)
    if not isinstance(data, dict):
        return None
    headline, oneliner = _bi(data.get("headline")), _bi(data.get("oneliner"))
    if headline is None or oneliner is None:
        return None
    known = {i.id for i in items}
    raw_summary, raw_claims = data.get("summary"), data.get("claims")
    if not isinstance(raw_summary, list) or not isinstance(raw_claims, list):
        return None
    summary = []
    for p in raw_summary:
        b = _bi(p)
        if b is None:
            return None
        srcs = p.get("sources")
        ids = [s for s in srcs if isinstance(s, str) and s in known] if isinstance(srcs, list) else []
        if ids:
            summary.append({**b, "sources": ids})
    claims = []
    for c in raw_claims:
        b = _bi(c)
        if b is None:
            return None
        claims.append(b)
    claims = claims[:config.CLAIMS_MAX]
    if not summary or len(claims) < 1:
        return None
    return Draft(headline, oneliner, summary, claims)
