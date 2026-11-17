"""Test doubles for the model clients."""


class FakeLLM:
    """Same interface as llm.LLM. Replies are consumed in order; an Exception reply yields None
    (as the real client does when its provider fails), a str reply is parsed like model text."""

    def __init__(self, replies: list, provider: str = "fake", model: str = "fake-model"):
        import llm
        self._extract = llm.extract_json
        self.replies = list(replies)
        self.provider, self.model = provider, model
        self.available = True
        self.calls: list[dict] = []

    def ask_json(self, job, system: str, user: str, max_tokens: int = 4000):
        self.calls.append({"job": job, "system": system, "user": user, "max_tokens": max_tokens})
        if not self.replies:
            return None
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            return None
        if isinstance(reply, str):
            return self._extract(reply)
        return reply
