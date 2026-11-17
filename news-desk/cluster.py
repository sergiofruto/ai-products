"""Group a topic's items into stories using the cluster model."""
import rules
from models import Item

SYSTEM = ("You group news items about the same event or story. Reply with JSON only: "
          '{"stories": [[n, ...], ...]} where each inner list holds the numbers of items covering '
          "the same story. Use each number at most once; omit items that match nothing.")


def cluster(llm, topic: str, items: list[Item]) -> list[list[Item]]:
    lines = [f"[{n}] {it.title} — {it.text[:200]}" for n, it in enumerate(items, 1)]
    reply = llm.ask_json("run", SYSTEM, f"Topic: {topic}\n\n" + "\n".join(lines), 4000)
    raw = reply.get("stories") if reply else None
    seen: set[int] = set()
    groups: list[list[Item]] = []
    for story in raw if isinstance(raw, list) else []:
        group = []
        for n in story if isinstance(story, list) else []:
            if isinstance(n, int) and not isinstance(n, bool) and 1 <= n <= len(items) and n not in seen:
                seen.add(n)
                group.append(items[n - 1])
        if group:
            groups.append(group)
    groups += [[it] for n, it in enumerate(items, 1) if n not in seen]
    groups.sort(key=lambda g: (rules.independent_count(g), max(i.published for i in g)), reverse=True)
    return groups
