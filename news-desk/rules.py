"""Pure scoring rules: no I/O, no DB, no model calls."""
from difflib import SequenceMatcher
from typing import Literal

import config
from models import Item

SIMILARITY_CHARS = 600
SIMILARITY_RATIO = 0.85


def independent_count(items: list[Item]) -> int:
    """Count independent sources: wire copies and near-identical texts collapse into one group,
    then distinct hosts are counted across the groups (one representative per group)."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        parent[find(j)] = find(i)

    for j, b in enumerate(items):
        for i in range(j):
            a = items[i]
            if a.wire and a.wire == b.wire:
                union(i, j)
            elif a.lang == b.lang:
                ta, tb = a.text[:SIMILARITY_CHARS], b.text[:SIMILARITY_CHARS]
                if ta.strip() and tb.strip() and SequenceMatcher(None, ta, tb).ratio() >= SIMILARITY_RATIO:
                    union(i, j)

    first_in_group: dict[int, Item] = {}
    for i, it in enumerate(items):
        first_in_group.setdefault(find(i), it)
    return len({it.host for it in first_in_group.values()})


def combine_votes(votes: list[str]) -> Literal["agreed", "disputed", "unverified"]:
    """Votes from available models only: supported | contradicted | not_found."""
    s = votes.count("supported")
    c = votes.count("contradicted")
    if s == 0 or c >= 2:
        return "unverified"
    if c == 0 and (s >= 2 or len(votes) == 1):
        return "agreed"
    return "disputed"


def band_for(total: int) -> str:
    if total >= config.BAND_HIGH:
        return "high"
    if total >= config.BAND_MEDIUM:
        return "medium"
    return "low"


def score(*, independent: int, has_primary: bool, verdicts: list[str], models_answered: int,
          avg_reliability: float, corrected: bool) -> dict:
    if independent >= 4:
        sources = config.SOURCE_COUNT_MAX
    else:
        sources = config.SOURCE_COUNT_POINTS.get(independent, 0)
    primary = config.PRIMARY_SOURCE_POINTS if has_primary else 0

    if verdicts:
        agreed = verdicts.count("agreed")
        raw = config.AGREEMENT_POINTS * agreed / len(verdicts) \
            - config.AGREEMENT_PENALTY_PER_REFUTED * verdicts.count("unverified")
        cap = config.AGREEMENT_CAP_BY_MODELS.get(models_answered, 0)
        agreement = round(max(0, min(raw, cap)))
    else:
        agreement = 0

    reliability = round(avg_reliability * config.RELIABILITY_WEIGHT)
    freshness = 0 if corrected else config.FRESHNESS_POINTS
    total = sources + primary + agreement + reliability + freshness
    return {"sources": sources, "primary": primary, "agreement": agreement,
            "reliability": reliability, "freshness": freshness, "total": total,
            "band": band_for(total)}


def top_sources(items: list[Item]) -> list[dict]:
    picks: list[dict] = []
    hosts: set[str] = set()

    def pick(it: Item | None, reason: str) -> None:
        if it is None or len(picks) >= 3 or it.host in hosts:
            return
        hosts.add(it.host)
        picks.append({"item_id": it.id, "source": it.source, "url": it.url, "reason": reason})

    def avail() -> list[Item]:
        return [it for it in items if it.host not in hosts]

    pick(next((it for it in items if it.kind == "primary"), None),
         "Primary source: published the original")
    a = avail()
    pick(min(a, key=lambda it: it.published, default=None), "First to report")
    a = avail()
    pick(max(a, key=lambda it: len(it.text), default=None), "Most detail")
    a = avail()
    pick(max(a, key=lambda it: it.reliability, default=None), "Most reliable outlet")
    return picks
