# ai-products

Three AI products I built and run, by [Sergio Gabriel Fruto](https://www.linkedin.com/in/sergio-gabriel-fruto/).

**The model talks, code decides.** In each one, models do what they're good at (language,
judgment, perception) and plain, tested code owns the facts: schedules, scores, sources and rules.

| Project | What it does | What it shows | Live | Stack |
|---|---|---|---|---|
| [**Clinic Voice Intake**](clinic-voice-intake/) | A bilingual voice agent that does intake for a physical therapy clinic and books a first evaluation. | Voice agent with tool calls; a Python API owns every slot and code; a "Behind the voice" panel shows each call. | [pt-intake-agent.vercel.app](https://pt-intake-agent.vercel.app) | ElevenAgents · FastAPI · Next.js 16 · Vercel |
| [**News Desk**](news-desk/) | A calm daily newspaper built from curated feeds, where every story shows its sources and a credibility score. | Several models check each other's claims; disagreement is shown, not hidden; the score is a tested formula, not a model's opinion. | Runs locally · public site coming | Python · Claude, OpenAI and xAI models · Flask · SQLite |
| [**Biomech Lab**](biomech-lab/) | Upload a yoga pose and get it recognized and scored from joint angles. Images never leave the browser. | AI running fully in the browser; a readiness gate that refuses to score a bad photo. | [biomech-lab.vercel.app](https://biomech-lab.vercel.app) | Next.js 16 · TypeScript · MediaPipe Pose · Vitest · Vercel |

## How I build with Claude

- **Spec, then plan, then code.** Design specs and implementation plans live in each project's `docs/`
  (see [News Desk](news-desk/docs/) and [Biomech Lab](biomech-lab/docs/)).
- **Rules the AI follows.** `CLAUDE.md` / `AGENTS.md` files set the stack, style and guardrails for the agent.
- **Tests first.** Scoring rules, clinic rules and citation checks are pure functions with unit tests.
- **Bounded and honest.** Daily cost caps, no invented links or slots, and clear messages when a model or input isn't good enough.

Each project's README has setup and run instructions.
