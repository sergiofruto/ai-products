"""Group a topic's items into stories using the cluster model, then merge the same event across topics."""
import rules
from models import Item

SYSTEM = ("You group news items about the same event or story. Reply with JSON only: "
          '{"stories": [[n, ...], ...]} where each inner list holds the numbers of items covering '
          "the same story. Use each number at most once; omit items that match nothing.")

MERGE_SYSTEM = ("Each numbered line is a candidate story from a news column. Find candidates that cover the "
                'same real-world event. Reply with JSON only: {"same": [[n, ...], ...]} where each inner list '
                "holds two or more numbers of candidates about the same event. Use each number at most once; "
                "omit candidates that have no duplicate.")


def rank_key(group: list[Item]):
    """Stories rank by independent sources, then recency."""
    return rules.independent_count(group), max(i.published for i in group)


def _numbers(raw, limit: int, seen: set[int]) -> list[int]:
    """Valid, unused 1-based numbers from one model-supplied list."""
    out = []
    for n in raw if isinstance(raw, list) else []:
        if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= limit and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def cluster(llm, topic: str, items: list[Item]) -> list[list[Item]]:
    lines = [f"[{n}] {it.title} — {it.text[:200]}" for n, it in enumerate(items, 1)]
    reply = llm.ask_json("run", SYSTEM, f"Topic: {topic}\n\n" + "\n".join(lines), 4000)
    raw = reply.get("stories") if reply else None
    seen: set[int] = set()
    groups = [[items[n - 1] for n in _numbers(story, len(items), seen)] for story in (raw if isinstance(raw, list) else [])]
    groups = [g for g in groups if g]
    groups += [[it] for n, it in enumerate(items, 1) if n not in seen]
    groups.sort(key=rank_key, reverse=True)
    return groups


def merge_across(llm, candidates: list[tuple[str, list[Item]]]) -> list[tuple[str, list[Item]]]:
    """One model call finds candidates (from any column) about the same event. Code merges each set into the
    candidate with the most independent sources (ties: the earlier one), keeping its topic and position and
    adding the others' items that aren't already there (by URL). The others are dropped."""
    if len(candidates) < 2:
        return candidates
    lines = [f"[{n}] ({topic}) {g[0].title} — {g[0].text[:150]}" for n, (topic, g) in enumerate(candidates, 1)]
    reply = llm.ask_json("run", MERGE_SYSTEM, "\n".join(lines), 2000)
    raw = reply.get("same") if reply else None
    if not isinstance(raw, list):
        return candidates
    out = list(candidates)
    dropped: set[int] = set()
    seen: set[int] = set()
    for same in raw:
        trial = set(seen)
        idx = [n - 1 for n in _numbers(same, len(candidates), trial)]
        if len(idx) < 2:  # a set of one merges nothing and must not use up its number
            continue
        seen = trial
        win = max(sorted(idx), key=lambda i: rules.independent_count(candidates[i][1]))  # max keeps the first on ties
        topic, group = candidates[win]
        merged, urls = list(group), {i.url for i in group}
        for i in sorted(idx):
            if i == win:
                continue
            dropped.add(i)
            for it in candidates[i][1]:
                if it.url not in urls:
                    urls.add(it.url)
                    merged.append(it)
        out[win] = (topic, merged)
    return [c for i, c in enumerate(out) if i not in dropped]
