"""Model clients: one small wrapper per provider, budget-checked, never raising."""
import json
import logging
from datetime import date

import budget as budget_mod
import config

log = logging.getLogger(__name__)

XAI_BASE_URL = "https://api.x.ai/v1"
# OpenAI's newer models use max_completion_tokens; xAI still takes max_tokens.
TOKEN_PARAM = {"openai": "max_completion_tokens", "xai": "max_tokens"}


def extract_json(text: str) -> dict | None:
    """Parse the outermost {...} in text; None if there is none or it is not a JSON object."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


class LLM:
    def __init__(self, provider: str, model: str, client, budget: budget_mod.Budget, today=date.today):
        self.provider, self.model, self.client, self.budget, self.today = provider, model, client, budget, today

    @property
    def available(self) -> bool:
        return self.client is not None

    def _call(self, system: str, user: str, max_tokens: int) -> tuple[str | None, int, int]:
        """Returns (text, input_tokens, output_tokens); text is None on a refusal."""
        if self.provider == "anthropic":
            r = self.client.messages.create(model=self.model, max_tokens=max_tokens, system=system,
                                            messages=[{"role": "user", "content": user}])
            tokens = (r.usage.input_tokens, r.usage.output_tokens)
            if r.stop_reason == "refusal":
                return None, *tokens
            # adaptive thinking may put thinking blocks before the text
            return "".join(b.text for b in r.content if b.type == "text"), *tokens
        r = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            **{TOKEN_PARAM[self.provider]: max_tokens})
        return r.choices[0].message.content or "", r.usage.prompt_tokens, r.usage.completion_tokens

    def ask_json(self, job, system: str, user: str, max_tokens: int = 4000) -> dict | None:
        if not self.available or not self.budget.can_spend(job, self.today()):
            return None
        try:
            text, tin, tout = self._call(system, user, max_tokens)
            self.budget.record(job, self.provider, self.model, tin, tout, self.today())
        except Exception as e:  # never raise; log the type only
            log.warning("%s/%s call failed: %s", self.provider, self.model, type(e).__name__)
            return None
        return extract_json(text) if text else None


def _client(provider: str, key: str):
    if not key:
        return None
    if provider == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=key)
    import openai
    return openai.OpenAI(api_key=key, base_url=XAI_BASE_URL if provider == "xai" else None)


def from_config(conn) -> dict:
    keys = {"anthropic": config.ANTHROPIC_API_KEY, "openai": config.OPENAI_API_KEY, "xai": config.XAI_API_KEY}
    b = budget_mod.Budget(conn, cap=config.AI_DAILY_CAP_USD, reserve=config.AI_PROJECTION_RESERVE_USD)
    mk = lambda p, m: LLM(p, m, _client(p, keys[p]), b)  # noqa: E731
    return {
        "writer": mk("anthropic", config.WRITER_MODEL),
        "cluster": mk("anthropic", config.CLUSTER_MODEL),
        "validators": [m for p, name in config.VALIDATORS if (m := mk(p, name)).available],
    }
