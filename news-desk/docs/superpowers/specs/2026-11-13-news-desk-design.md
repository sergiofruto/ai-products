# News Desk: design (MVP)

Date: 2026-11-13 · Owner: Sergio · Status: draft for approval

## Why

News sites push clickbait, ads and pop-ups. Sergio wants a calm morning paper he actually uses,
built from many sources, where every story can be checked: who reported it, which claims hold
up, and how credible it is. It's also something Claude can read in a Claude Code session, so
"what happened with chips this week?" has a grounded answer.

## What it is

A local news service in `ai-products/news-desk/`:

1. **Home (layout A, "the newspaper"):** one column per topic. Each story has a headline, one plain
   sentence, a source count and a credibility badge. Print-like, calm, no images required.
2. **Read view:** click a story to read a ~3-minute summary synthesized from all its sources,
   with links to the originals. Normal reading, nothing else on the page.
3. **Go deep (terminal view):** a button on the read view switches to a dark, monospace view with
   four panels:
   - **Article:** the synthesized text, with key quotes kept verbatim and attributed, plus all original links.
   - **Validation (2 models):** the story's key claims as a list. Each claim is checked by two
     different models against the source texts and marked agreed ✓, disputed ~ or unverified ✗,
     with each model's verdict shown. Disagreement between the models is visible, not hidden.
   - **Projections:** what to watch next (dated events, if any), plausible outcomes, and what would change them.
     Clearly labeled as model speculation.
   - **Source map:** the **top 3 sources** highlighted, each with a one-line reason (e.g.
     "primary source, published the data", "first to report", "most detail"), then the rest of
     the sources in a smaller list with type (primary / wire / outlet) and publish time.
4. **Credibility score (0–100)** on every story: a badge on Home, the breakdown in Go deep.

Mockups from the brainstorm: `layout.html` (option A chosen) and `go-deep.html`.

## Principles

- **The model talks, code decides.** Models summarize, extract claims and judge claims. Code
  computes the score, picks the top 3 sources, checks that every source id or URL a model cites
  exists in the input, and drops anything that doesn't.
- **No invented facts or links.** A model can only cite sources it was given. Summaries carry
  source ids; links shown to the user come from the database, never from model text.
- **Transparent score.** The score is a formula over things you can see, never one model's opinion.
- **Bounded cost.** A daily spend cap, as in the Security Agent (`budget.py`).

## Credibility score (code, not model)

Starting weights. The formula is a pure, tested function and the weights live in config.

| Factor | Points | How it's measured |
|---|---|---|
| Independent sources | 0–30 | Count of distinct outlets after collapsing wire copies (same wire credit, or near-identical text). 1 → 5, 2 → 15, 3 → 22, 4+ → 30 |
| Primary source | 0–20 | 20 if any source is primary (official body, company, court, data publisher) |
| Model agreement | 0–30 | Share of claims both models mark ✓ × 30. Each claim one model rejects costs 5 more |
| Outlet track record | 0–15 | Average reliability of the outlets, 0–1 from `sources.yaml`, × 15 |
| Freshness / corrections | 0–5 | 5 unless a source reports a correction or update that changes a claim |

Bands: 80+ high, 60–79 medium, below 60 low. Go deep shows each factor's points.

## Pipeline (one run)

1. **Fetch:** pull RSS/Atom feeds from a curated list (`sources.yaml`). Each entry has: name, url, topic(s),
   type (primary/wire/outlet), reliability 0–1 and language. Where the feed only has a teaser,
   fetch the article page and extract the main text. Skip paywalled pages, and respect robots.txt.
   No general web crawling in the MVP.
2. **Group into stories:** per topic, a cheap model clusters items from the last 24 h into
   stories. Code validates the output (each item in at most one story; ids exist). Stories
   with 1 source are kept but scored low.
3. **Rank per topic:** by independent source count, then recency. Keep the top N stories per column (default 5).
4. **Write:** for each kept story, the writer model produces the headline, one-liner, summary
   (with source ids per paragraph) and a list of 3–6 key claims.
5. **Validate:** two different models each judge every claim against the source texts.
6. **Score + source map:** code.
7. **Projections:** generated on first "Go deep" click and cached (keeps the daily run cheap).
8. **Export:** write `exports/YYYY-MM-DD.md` (and JSON) with every story, score, claims and
   links, so Claude can read it in a session.

Run by hand (`python main.py run`) and, once it's stable, every morning at 07:00 via launchd, like the Security Agent.

## Stack

Python, `feedparser`, `requests`, Flask with server-rendered templates for the UI at `127.0.0.1:5008`, SQLite, pytest,
`anthropic` SDK, `.env` for keys (gitignored), and the same budget cap pattern. Local only, with no deploy in the MVP.

## Goals (MVP)

- One morning run produces a Home with 4–5 topic columns and up to 5 stories each.
- Read view and Go deep work for every story, with score breakdown, top 3 sources, two-model validation and projections.
- A daily export Claude can read.
- Daily cost under the cap (default $1).

## Non-goals (MVP)

- Deploying it publicly, accounts, mobile app, push notifications.
- General web crawling, search engines, social media (X, Reddit).
- Personalization that learns from clicks.
- Geographic maps.
- Bypassing paywalls.

## Anti-goals (it fails if…)

- It surfaces clickbait or rage-bait because many outlets copied it.
- A score looks precise but can't be explained from its parts.
- Any link, quote or number on screen isn't traceable to a fetched source.
- It costs more than expected without warning.

## Decisions settled after review (Claude's calls; Sergio can override)

- **Location:** the repo folder is `news-desk/` in `ai-products`.
  The mockups are in `docs/mockups/` (`layout.html` with option A chosen, and `go-deep.html`). They're HTML fragments from the
  brainstorm tool, so read them for structure, not exact styling.
- **Verdict rules (SUPERSEDED by "Three-model rules" below; kept for history):** each model returns `supported`, `contradicted` or `not_found` per claim.
  - ✓ agreed = both models say `supported`
  - ✗ unverified = both say `not_found`, or either one says `contradicted`
  - ~ disputed = everything else (the models disagree)
  - **Model agreement points** = 30 × (✓ claims / all claims) − 5 per ✗ claim, floored at 0. A ~ claim costs nothing beyond not counting as ✓.
- **One model missing** (no key, or the provider is down): the story still ships with its validation marked "1 model".
  Each claim's verdict comes from that model alone, and the agreement factor is capped at 15 of its 30 points. The score must never
  look as strong as a two-model check.
- **Budget:** the default cap is $1/day, and $0.25 of it is held back for on-demand projections (like the Security Agent's digest reserve).
  - **Order of work:** validate stories by rank, across topics round-robin, so every column gets its best stories first.
  - **If the cap is reached:** stop adding stories. A smaller paper beats a story without validation.
  - **Cost control:** each model checks all of a story's claims in one call, against trimmed source texts (about 1,500 characters per source).
  - **Estimate:** the cap and `MODEL_PRICES` live in config. The run logs its estimated cost before it starts.
- **Days and history:** each day is its own paper, and a second run on the same day replaces it. History
  for "what happened this week" comes from the daily exports and the database, which keeps every day. Linking a
  running story across days is out of the MVP.

## Left to the builder

Clustering prompt, extraction approach for article text, the exact template look (follow the
mockups), the DB schema, and the test strategy (the score, the top-3 picker, the wire-copy
collapsing and the citation checks must be unit tested with fixtures).

## Sergio's answers (2026-11-13)

- **Validators: three models from three providers:** Claude (Anthropic), GPT (OpenAI) and Grok (xAI).
  Sergio's reasoning: three opinions are more balanced than two, and Grok is closer to X/Twitter.
  This **replaces "2 models" everywhere above**: the Go deep panel, the verdict rules and the score.
- **Language: English and Spanish.** Home gets an EN/ES toggle. *Claude's interpretation:* the writer produces
  both versions of each story in one call, so the toggle switches instantly. Quotes stay in their original language.
- **Topics:** Tech, AI and Stocks first, then general news. *Claude's proposal for columns:* **AI · Tech · Stocks ·
  World · Argentina.** Argentina is a guess; Sergio confirms or swaps it.

## Three-model rules (Claude's calls)

Each available model returns `supported`, `contradicted` or `not_found` per claim. With *n* models answering:
- ✓ agreed = more than half say `supported`, and none says `contradicted`
- ✗ unverified = none says `supported`, or more than half say `contradicted`
- ~ disputed = everything else
- **Agreement points:** 30 × (✓ / claims) − 5 per ✗, floored at 0, then capped by how many models answered:
  3 models → 30, 2 → 24, 1 → 15. Go deep shows each model's verdict per claim and a "2 of 3 models" label when one is missing.
- **Grok:** in the MVP it validates against the same fetched source texts as the others, with no live X search. Using its X
  search as an extra source (e.g. "what are insiders saying") is a later feature, with its own cost.
- **Keys:** `ANTHROPIC_API_KEY` (exists), `OPENAI_API_KEY` and `XAI_API_KEY`, in `news-desk/.env` (gitignored). Each goes in the file, never in chat.
  A missing key just means that model is skipped.
- **Budget:** three validators cost more, so the default cap is **$1.50/day**, with $0.25 held back for projections.
  Validators use each provider's cheapest capable model, and the model names live in config.

## Sources (Claude's call)

The builder proposes `sources.yaml`: about 4–8 feeds per column, mixing primary sources (official bodies, company
blogs, regulators), wires and outlets in English and Spanish. Each gets a reliability score with a one-line reason.
**Sergio reviews it before the first real run.** That's a step in the plan, not an afterthought.

## Stocks guardrail

Stocks stories report what happened and what to watch (earnings dates, filings, guidance). Projections never
recommend buying or selling, and never give price targets as advice.
