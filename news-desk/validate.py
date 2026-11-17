"""Three-model claim validation: each available model votes on every claim against the sources."""
import config
import rules

VALID = {"supported", "contradicted", "not_found"}

SYSTEM = (
    "You are a fact-checking assistant. Judge each numbered claim ONLY against the given source texts, "
    "using no outside knowledge. For each claim answer exactly one of: supported (a source states it), "
    "contradicted (a source states the opposite), not_found (no source addresses it). "
    'Reply with JSON only: {"votes": [...]} with exactly one value per claim, in claim order.'
)


def _prompt(claims: list[dict], items: list) -> str:
    cl = "\n".join(f"{n}. {c['en']}" for n, c in enumerate(claims, 1))
    src = "\n".join(f"{i.id}: {i.text[:config.SOURCE_TEXT_CHARS]}" for i in items)
    return f"CLAIMS ({len(claims)}):\n{cl}\n\nSOURCES:\n{src}\n\nReturn {{\"votes\": [...]}} with {len(claims)} values."


def check(validators: list, claims: list[dict], items: list) -> tuple[list[str], dict[str, list[str]]]:
    n = len(claims)
    votes: dict[str, list[str]] = {}
    if n:
        user = _prompt(claims, items)
        for m in validators:
            if not m.available:
                continue
            data = m.ask_json("run", SYSTEM, user, max_tokens=4000)
            v = data.get("votes") if isinstance(data, dict) else None
            if isinstance(v, list) and len(v) == n and all(isinstance(x, str) and x in VALID for x in v):
                votes[m.provider] = v
    verdicts = [rules.combine_votes([v[i] for v in votes.values()]) for i in range(n)]
    return verdicts, votes
