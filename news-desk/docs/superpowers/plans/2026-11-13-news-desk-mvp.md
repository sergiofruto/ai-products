# News Desk MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local news service. It fetches curated feeds, groups items into stories, writes them in EN+ES, validates each claim with three models, scores credibility in code, and serves a newspaper-style Home with a read view and a "Go deep" terminal view.

**Architecture:** Python pipeline (`fetch → cluster → write → validate → score → persist → export`) behind `python main.py run`, and a Flask app (`python main.py serve`) on 127.0.0.1:5008 reading the same SQLite DB. Models only produce text and judgments as JSON. Pure, tested functions compute the score, the claim verdicts, the wire-copy collapse, the top-3 sources and the citation checks.

**Tech Stack:** Python 3.11+, feedparser, requests, trafilatura, PyYAML, anthropic SDK, openai SDK (also used for xAI via `base_url`), Flask + Jinja templates, SQLite, pytest, python-dotenv.

**Spec:** `news-desk/docs/superpowers/specs/2026-11-13-news-desk-design.md`. Mockups are in `news-desk/docs/mockups/`.

## Global Constraints

- Everything lives in `claude-code-agents/news-desk/`. All commands run from that folder, using `.venv/bin/python`.
- Keys come from `news-desk/.env` (gitignored): `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY`. A missing key means that model is skipped. Never log key values.
- Web server binds `127.0.0.1` only, port `5008` (env `WEB_PORT`).
- Budget: `AI_DAILY_CAP_USD` default `1.50`. `AI_PROJECTION_RESERVE_USD` default `0.25`. The pipeline run may spend up to cap − reserve, and projections may spend up to the full cap. An unknown model is priced like the most expensive known model, never as free.
- Columns, in order: `ai`, `tech`, `stocks`, `world`, `argentina`. Display names: "AI", "Tech", "Stocks", "World", "Argentina".
- Up to 5 stories per column (`STORIES_PER_TOPIC=5`). Clustering window: the last 24 h.
- Claims per story: 3–6. Source text sent to validators is trimmed to 1,500 characters per source.
- Every link, quote and number shown must trace to a fetched item. Links on screen come from the `items` table, never from model text.
- Score weights and bands exactly as in the spec: sources 1→5, 2→15, 3→22, 4+→30. Primary source 20. Agreement 30 × (✓/claims) − 5 per ✗, floored at 0, capped at 30/24/15 for 3/2/1 models. Reliability avg × 15. Freshness 5, or 0 when corrected. Bands: 80+ high, 60–79 medium, <60 low.
- Stocks guardrail: projections never recommend buying or selling, and never give price targets.
- Git: work on branch `feat/news-desk`, created from the current HEAD. Stage only `news-desk/` paths. The repo has unrelated uncommitted work, so never use `git add -A`.

## Review Focus

1. **A feed is down, slow, or returns garbage.** That source is skipped and logged, and the run continues with the rest (test in Task 2).
2. **A model returns malformed JSON, or cites item ids it wasn't given.** Invalid ids are dropped, and a story that ends up with nothing valid is skipped. The run never crashes, and no invented link appears (tests in Tasks 5, 6 and 7).
3. **The budget runs out mid-run, or `ANTHROPIC_API_KEY` is missing.** The stories done so far are saved, and Home shows a banner ("Stopped at today's cost cap" / "Writer model unavailable, showing the last paper"). Yesterday's paper is never wiped by a failed run (test in Task 8).
4. **A column has no stories.** It shows "Nothing solid today" instead of an empty column or an error (test in Task 10).
5. **Feed titles or text contain HTML or `<script>`.** The text is stripped to plain text at fetch, and Jinja autoescape stays on, so nothing executes in the page (tests in Tasks 2 and 10).

---

### Task 1: Scaffold, config, DB and budget

**Files:**
- Create: `requirements.txt`, `.gitignore` (`.env`, `.venv/`, `*.db*`, `exports/`, `__pycache__/`), `.env.example`, `config.py`, `db.py`, `budget.py`, `tests/conftest.py`, `tests/test_budget.py`

**Interfaces:**
- Produces: `config` module constants (all values from Global Constraints, plus `DB_PATH`, `EXPORT_DIR`, `TOPICS: list[tuple[str, str]]`, `MODEL_PRICES: dict[str, tuple[float, float]]`, `WRITER_MODEL="claude-sonnet-5-5"`, `CLUSTER_MODEL="claude-haiku-5-5"`, `VALIDATORS: list[tuple[str, str]]` = provider/model pairs, defaulting to `[("anthropic","claude-haiku-5-5"), ("openai", env OPENAI_VALIDATOR_MODEL), ("xai", env XAI_VALIDATOR_MODEL)]`)
- Produces: `db.connect(path: str) -> sqlite3.Connection` (creates the schema below, WAL mode, `row_factory=sqlite3.Row`)
- Produces: `budget.Budget(conn, cap, reserve)` with `can_spend(job: Literal["run","projection"], day) -> bool` and `record(job, provider, model, input_tokens, output_tokens, day) -> float`, plus `budget.cost_usd(model, in, out) -> float`

Schema (fixed, because later tasks and the web read it):
```sql
items(id TEXT PRIMARY KEY, day TEXT, topic TEXT, source TEXT, kind TEXT, url TEXT, host TEXT,
      title TEXT, published TEXT, text TEXT, lang TEXT, reliability REAL, wire TEXT)
papers(day TEXT PRIMARY KEY, created_at TEXT, status TEXT, note TEXT)   -- status: ok | partial | failed
stories(id TEXT PRIMARY KEY, day TEXT, topic TEXT, rank INTEGER,
        headline_en TEXT, headline_es TEXT, oneliner_en TEXT, oneliner_es TEXT,
        summary_json TEXT, score INTEGER, breakdown_json TEXT, top_sources_json TEXT, models_answered INTEGER)
story_items(story_id TEXT, item_id TEXT)
claims(id INTEGER PRIMARY KEY, story_id TEXT, idx INTEGER, text_en TEXT, text_es TEXT, verdict TEXT)
claim_votes(claim_id INTEGER, provider TEXT, vote TEXT)
projections(story_id TEXT, lang TEXT, body_json TEXT, created_at TEXT, PRIMARY KEY(story_id, lang))
ai_usage(day TEXT, job TEXT, provider TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER, cost_usd REAL)
```

- [ ] **Step 1:** Create the venv (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`) and branch (`git checkout -b feat/news-desk`).
- [ ] **Step 2: Write failing tests** in `tests/test_budget.py`:
  - `test_run_stops_before_reserve`: cap 1.50, reserve 0.25, record a run cost totalling 1.25. Then `can_spend("run", d)` is False and `can_spend("projection", d)` is True.
  - `test_projection_stops_at_cap`: total 1.50 recorded, so `can_spend("projection", d)` is False.
  - `test_unknown_model_priced_as_most_expensive`: `cost_usd("mystery", 1_000_000, 0) == max(p[0] for p in MODEL_PRICES.values())`.
  - `test_spend_is_per_day`: a cost recorded yesterday doesn't count today.
  
  `tests/conftest.py` gives a `conn` fixture (`db.connect(":memory:")`).
- [ ] **Step 3:** Run `.venv/bin/python -m pytest tests/test_budget.py -v`. Expected: FAIL (module missing).
- [ ] **Step 4:** Implement `config.py`, `db.py` and `budget.py`. `budget.py` mirrors `security-agent/budget.py`, with the reserve logic inverted: the reserve is held for `projection`. `MODEL_PRICES` gets an entry for each default model. Put a comment with the date checked, and verify the prices on each provider's pricing page; if a price can't be verified, leave the model out so it's priced as the most expensive.
- [ ] **Step 5:** Run the tests again. Expected: PASS.
- [ ] **Step 6:** Commit (`git add news-desk/ && git commit -m "news-desk: scaffold, config, db, budget"`).

### Task 2: Sources and fetching

**Files:**
- Create: `sources.yaml`, `models.py`, `fetch.py`, `tests/fixtures/feed_ok.xml`, `tests/fixtures/feed_html.xml`, `tests/test_fetch.py`

**Interfaces:**
- Produces: `models.Item` frozen dataclass: `id: str` (sha1(url)[:12]), `topic: str`, `source: str`, `kind: Literal["primary","wire","outlet"]`, `url: str`, `host: str`, `title: str`, `published: datetime` (UTC), `text: str`, `lang: Literal["en","es"]`, `reliability: float`, `wire: str | None`
- Produces: `fetch.load_sources(path) -> list[dict]` (keys: `name, url, topics, kind, reliability, lang, reason`)
- Produces: `fetch.fetch_all(sources, now: datetime, get=requests.get, window_hours=24) -> list[Item]`
- Produces: `fetch.detect_wire(text: str) -> str | None`. It matches attributions for Reuters, AP / Associated Press, AFP, EFE, and Noticias Argentinas (`\bNA\b` only in "(NA)" / "Agencia NA" form). It returns a normalized name.

- [ ] **Step 1: Write failing tests:**
  - `test_parses_feed_within_window`: the fixture has 3 entries, one older than 24 h, so 2 Items are returned with the source's topic, kind, reliability and lang.
  - `test_html_is_stripped`: an entry whose title is `<b>Hi</b><script>x()</script>` gives `item.title == "Hi"` with no `<` in the title or text.
  - `test_broken_feed_is_skipped`: a `get` that raises `requests.Timeout` for one source and returns the fixture for another. The result has only the second source's items, and no exception is raised.
  - `test_detect_wire`: `detect_wire("... (Reuters) - ...") == "reuters"`, `detect_wire("MADRID, 3 nov (EFE).") == "efe"`, `detect_wire("plain text") is None`.
  - `test_one_item_per_topic`: a source with `topics: [ai, tech]` gives one Item per topic for the same entry, with different ids (sha1 of url+topic).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Use feedparser on the `get` response body. When an entry's summary is shorter than 400 chars, fetch the page and run `trafilatura.extract`. If that fails or returns `None`, keep the summary. Skip a URL when robots.txt disallows it (`urllib.robotparser`, cached per host). Truncate `text` to 6,000 chars. Draft `sources.yaml` with 4–8 feeds per topic, mixing primary/wire/outlet and EN/ES. Give each a `reliability` and a one-line `reason`, and check each feed once with feedparser.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit.

### Task 3: Pure scoring rules

**Files:**
- Create: `rules.py`, `tests/test_rules.py`

**Interfaces:**
- Consumes: `models.Item`
- Produces:
  - `rules.independent_count(items: list[Item]) -> int`
  - `rules.combine_votes(votes: list[str]) -> Literal["agreed","disputed","unverified"]`. Votes are from available models only, each `supported|contradicted|not_found`.
  - `rules.score(*, independent: int, has_primary: bool, verdicts: list[str], models_answered: int, avg_reliability: float, corrected: bool) -> dict` with keys `sources, primary, agreement, reliability, freshness, total, band`
  - `rules.top_sources(items: list[Item]) -> list[dict]` (≤3 entries `{item_id, source, url, reason}`)

`independent_count` collapses wire copies: items sharing the same non-null `wire` count once. Items of the same `lang` whose first 600 chars have a `difflib.SequenceMatcher` ratio ≥ 0.85 count once. Then distinct `host`s are counted across the groups.

`top_sources` picks in order, never repeating a host:
1. the first `primary` item: "Primary source: published the original"
2. the earliest `published`: "First to report"
3. the longest `text`: "Most detail"
4. if there are still fewer than 3, the highest `reliability`: "Most reliable outlet"

- [ ] **Step 1: Write failing tests** (spec values):
  - `test_sources_points`: independent 0/1/2/3/4/7 → 0/5/15/22/30/30.
  - `test_combine_three`:
    - `[s,s,s]` → agreed
    - `[s,s,n]` → agreed
    - `[s,s,c]` → disputed
    - `[s,n,n]` → disputed
    - `[n,n,n]` → unverified
    - `[c,c,s]` → unverified
  - `test_combine_two_and_one`:
    - `[s,s]` → agreed
    - `[s,n]` → disputed
    - `[n,n]` → unverified
    - `[s,c]` → disputed
    - `[s]` → agreed
    - `[c]` → unverified
  - `test_agreement_cap_by_models`: 4 claims all agreed. Agreement is 30 with 3 models, 24 with 2, 15 with 1.
  - `test_agreement_penalty_floor`: 4 claims, 1 agreed, 3 unverified, 3 models: 30×0.25 − 15 → 0, never negative.
  - `test_full_example`: independent 3, primary True, verdicts [agreed]*4, 3 models, avg reliability 0.8, not corrected → `{"sources":22,"primary":20,"agreement":30,"reliability":12,"freshness":5,"total":89,"band":"high"}`.
  - `test_bands`: 80 → high, 79 → medium, 60 → medium, 59 → low.
  - `test_wire_copies_count_once`: 3 items with `wire="reuters"` on 3 hosts, plus 1 own-reporting item → 2.
  - `test_near_identical_text_counts_once`: same text on 2 hosts → 1.
  - `test_top_sources_order_and_no_repeat_host`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement. Round reliability points with `round()`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit.

### Task 4: Model clients

**Files:**
- Create: `llm.py`, `tests/fakes.py`, `tests/test_llm.py`

**Interfaces:**
- Consumes: `budget.Budget`, `config`
- Produces:
  - `llm.LLM(provider: str, model: str, client, budget: Budget, today=date.today)` with `.available -> bool` and `.ask_json(job, system: str, user: str, max_tokens: int) -> dict | None`
  - `llm.from_config(conn) -> dict[str, LLM]` with keys `writer`, `cluster`, `validators` (the last is a list of LLM, one per provider whose key exists)
  - `tests/fakes.FakeLLM(replies: list[dict | str | Exception])`, which has the same interface and records the prompts it receives

`ask_json` returns None, and never raises, when:
- the budget forbids the job
- the provider raises
- the reply isn't valid JSON after extracting the outermost `{...}`

Every successful call is recorded in the budget with real token counts. Anthropic uses `anthropic.Anthropic().messages.create`. OpenAI and xAI use `openai.OpenAI(api_key=..., base_url=...)` with `response_format={"type":"json_object"}`, and xAI's `base_url` is `https://api.x.ai/v1`. Check the xAI and OpenAI model ids against each provider's `/v1/models` once keys exist, and set the defaults via env.

- [ ] **Step 1: Write failing tests** with stub clients:
  - `test_parses_json_inside_text` (reply `"Here: {\"a\":1}"` → `{"a":1}`)
  - `test_bad_json_returns_none`
  - `test_provider_error_returns_none`
  - `test_records_usage`
  - `test_blocked_by_budget_makes_no_call`
  - `test_from_config_skips_missing_keys` (monkeypatched env with only an Anthropic key → `validators` has length 1)
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5:** Commit.

### Task 5: Clustering

**Files:**
- Create: `cluster.py`, `tests/test_cluster.py`

**Interfaces:**
- Consumes: `LLM.ask_json`, `Item`
- Produces: `cluster.cluster(llm, topic: str, items: list[Item]) -> list[list[Item]]`

The prompt lists the items as `[n] title — first 200 chars` and asks for `{"stories": [[n, ...], ...]}`. Code then:
- drops unknown indexes
- keeps each item in only its first story
- turns unassigned items into singletons
- returns groups sorted by `rules.independent_count` descending, then by newest `published`

If the model returns None, every item becomes a singleton.

- [ ] **Step 1: Write failing tests** with FakeLLM:
  - `test_groups_follow_model`
  - `test_unknown_and_duplicate_ids_ignored`
  - `test_unassigned_become_singletons`
  - `test_model_failure_falls_back_to_singletons`
  - `test_sorted_by_independent_sources`
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit.

### Task 6: Writing and citation checks

**Files:**
- Create: `write.py`, `tests/test_write.py`

**Interfaces:**
- Consumes: `LLM.ask_json`, `Item`
- Produces:
  - `write.Draft` dataclass: `headline: dict[str,str]` (`en`, `es`), `oneliner: dict[str,str]`, `summary: list[dict]` (each `{"en": str, "es": str, "sources": list[str]}`, where sources are item ids), `claims: list[dict]` (each `{"en": str, "es": str}`)
  - `write.write_story(llm, items: list[Item]) -> Draft | None`

The prompt gives each item as `id: source — title — text[:1500]`. It asks for the JSON shape above in EN and ES, with verbatim quotes kept in the original language and attributed. It asks for 3–6 checkable factual claims, and for no recommendations on stocks. Code then:
- removes unknown ids from each paragraph's `sources`
- drops paragraphs left with no sources
- truncates claims to 6
- returns None if there are no paragraphs, fewer than 1 claim, or a missing `en`/`es` field

- [ ] **Step 1: Write failing tests:**
  - `test_valid_draft`
  - `test_unknown_source_ids_removed`
  - `test_paragraph_without_valid_sources_dropped`
  - `test_all_paragraphs_invalid_returns_none`
  - `test_claims_capped_at_six`
  - `test_missing_spanish_returns_none`
  - `test_model_failure_returns_none`
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit.

### Task 7: Three-model validation

**Files:**
- Create: `validate.py`, `tests/test_validate.py`

**Interfaces:**
- Consumes: `LLM.ask_json`, `rules.combine_votes`, `Item`
- Produces: `validate.check(validators: list[LLM], claims: list[dict], items: list[Item]) -> tuple[list[str], dict[str, list[str]]]`. The tuple is the verdicts per claim and the votes keyed by provider, for providers that answered validly.

Each validator gets a single call per story. The input is the claims in English, plus the sources as `id: text[:1500]`. It must return `{"votes": [...]}`, with one value per claim from `supported|contradicted|not_found`. A reply of the wrong length, or with any other value, counts as that model not answering. If no model answers, every verdict is `unverified`.

- [ ] **Step 1: Write failing tests:**
  - `test_three_models_majority`
  - `test_bad_length_reply_ignored` (that provider is absent from the votes)
  - `test_invalid_vote_value_ignored`
  - `test_no_model_answers_all_unverified`
  - `test_source_text_trimmed_to_1500` (assert on the prompt recorded by FakeLLM)
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit.

### Task 8: The run: rank, budget, persist, export

**Files:**
- Create: `pipeline.py`, `export.py`, `main.py` (`run` and `serve` subcommands, with logging to `news-desk.log`), `tests/test_pipeline.py`

**Interfaces:**
- Consumes: everything above
- Produces:
  - `pipeline.run(conn, now: datetime, llms: dict, fetch_fn) -> dict` returning `{"status": "ok"|"partial"|"failed", "stories": int, "note": str}`
  - `export.write(conn, day: str, out_dir: Path) -> tuple[Path, Path]` (md and json)

Flow:
1. Fetch.
2. If `llms["writer"]` is unavailable, return `failed` and leave the existing paper untouched, with note "Writer model unavailable".
3. Cluster per topic.
4. Build the work queue round-robin across `TOPICS`, by rank (rank 1 of each topic, then rank 2 of each, and so on), up to `STORIES_PER_TOPIC`.
5. For each story: write, validate, score (`corrected=False` in the MVP), and take the top sources.
6. Stop when `budget.can_spend("run")` is False. The status becomes `partial`, with note "Stopped at today's cost cap".
7. In one transaction, delete that day's stories, claims, votes and story_items, then insert the new ones and upsert `papers`. A re-run replaces the day.
8. Export.

The md export lists, per topic:
- headline (EN)
- score and band
- one-liner
- claims with their verdicts
- source links

The json export holds the same data, structured.

- [ ] **Step 1: Write failing tests** (FakeLLMs, fixture Items):
  - `test_end_to_end_two_topics` (the stories, claims, votes and paper rows exist, and the export files exist and contain the headline)
  - `test_round_robin_order` (with a budget that allows exactly 2 stories, the run saves rank 1 of `ai` and rank 1 of `tech`, not two from `ai`)
  - `test_budget_stop_is_partial_and_keeps_done_stories`
  - `test_missing_writer_keeps_previous_paper` (yesterday's/today's existing rows are unchanged, and the status is failed)
  - `test_rerun_replaces_day`
  - `test_story_skipped_when_write_returns_none`
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit.

### Task 9: Projections on demand

**Files:**
- Create: `projections.py`, `tests/test_projections.py`

**Interfaces:**
- Consumes: `LLM.ask_json` (writer model, job `"projection"`), DB
- Produces: `projections.get(conn, llm, story_id: str, lang: str) -> dict | None` returning `{"watch": [{"date": str|None, "what": str}], "outcomes": [str], "would_change": [str]}`

Cached in the `projections` table, so a second call makes no model call. The system prompt states that the output is speculation, and that it must never recommend buying, selling or holding or give price targets. For `stocks` stories, code also drops any `outcomes` line matching `(?i)\b(buy|sell|price target|comprar|vender|precio objetivo)\b`.

- [ ] **Step 1: Write failing tests:**
  - `test_generates_and_caches`
  - `test_budget_blocked_returns_none`
  - `test_stocks_advice_lines_removed`
  - `test_prompt_contains_guardrail`
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit.

### Task 10: Web: Home, read view, Go deep

**Files:**
- Create: `web.py` (Flask app factory `create_app(conn_factory, llm_factory)`), `templates/base.html`, `templates/home.html`, `templates/story.html`, `templates/deep.html`, `static/style.css`, `tests/test_web.py`

**Interfaces:**
- Consumes: DB, `projections.get`
- Produces routes:
  - `/` (`?lang=en|es`, default `en`). The chosen language is remembered in a cookie.
  - `/story/<id>`
  - `/story/<id>/deep`

**Home** follows mockup A:
- the date and "updated HH:MM"
- an EN/ES toggle
- five columns in `TOPICS` order (stacked on narrow screens), each story showing:
  - headline
  - one-liner
  - "N sources"
  - a score badge colored by band
- a banner when the paper's status is `partial` or `failed`, showing its note
- "Nothing solid today" for an empty column
- when there's no paper at all: "No paper yet. Run `python main.py run`."

**Read view:**
- headline
- "Synthesized from N sources · X min read" (words / 200)
- summary paragraphs, each followed by its source names linked to `items.url`
- a "&gt;_ Go deep" button

**Go deep** follows `go-deep.html`, dark and monospace, with four panels:
1. **Article:** summary plus every source link.
2. **Validation:** each claim with ✓/~/✗ and each provider's vote. Show "2 of 3 models" when fewer than 3 answered.
3. **Projections:** via `projections.get`, labeled "Model speculation". If it returns None, show "Projections unavailable (cost cap or model)".
4. **Source map:** the top 3 sources highlighted with their reasons, then the remaining sources with kind and time.

The score breakdown is shown as five rows with points.

- [ ] **Step 1: Write failing tests** (Flask test client, seeded DB):
  - `test_home_shows_columns_and_badge`
  - `test_home_spanish_toggle`
  - `test_empty_column_message`
  - `test_partial_banner`
  - `test_no_paper_message`
  - `test_story_links_come_from_items` (an href equals the `items.url`)
  - `test_deep_shows_votes_and_breakdown`
  - `test_deep_two_of_three_label`
  - `test_script_in_title_is_escaped` (a seeded headline `<script>alert(1)</script>` appears escaped)
  - `test_unknown_story_404`
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit.

### Task 11: Source review, live run, README

**Files:**
- Create: `README.md` (what it is, setup, keys, run/serve, cost cap, design link)
- Modify: `sources.yaml` (after Sergio's review)

- [ ] **Step 1:** Show Sergio `sources.yaml` as a table (name, topic, kind, lang, reliability, reason). **Wait for his edits or approval.** Apply them.
- [ ] **Step 2:** Run the full test suite: `.venv/bin/python -m pytest -q`. Expected: all pass.
- [ ] **Step 3:** Live run: `.venv/bin/python main.py run`. Expected:
  - the status is ok or partial
  - at least 3 topics have stories
  - `ai_usage` totals ≤ `cap − reserve`
  - the export files exist
- [ ] **Step 4:** Run `.venv/bin/python main.py serve`, then open http://127.0.0.1:5008. Check:
  - Home in EN and ES
  - one read view
  - one Go deep with projections generated
  
  Report anything that looks wrong to Sergio with a screenshot.
- [ ] **Step 5:** Commit README and the reviewed sources.
