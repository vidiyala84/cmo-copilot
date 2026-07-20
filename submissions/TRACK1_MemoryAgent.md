# Submission — Track 1: MemoryAgent

**Tagline:** A marketing-decision copilot that measurably gets
better every session — because it **learns from experience which of its own calls to
override**, validates that the change *mattered* against its own history, and enforces
it reliably.

> **Headline result (100-question benchmark, real Qwen on Qwen Cloud):** the fuzzy,
> prose version of memory *discovers* the right rules but **oscillates and never
> converges** (an honest negative result we report in full). The version that works
> **learns each gate as a structured condition from the session history** (a decision
> tree — no hand-set thresholds; it discovered e.g. `cvr_drop > 0.53 → fix_tracking`),
> keeps only the gates history shows *mattered* (lift > 0), and enforces them
> deterministically. Composed with the Agent Society it converges **74% → 100% over
> four sessions and holds** — enforcement costs zero LLM calls. Full story & numbers:
> `../docs/SUBMISSION.md` §3–4; loop diagram in `../docs/ARCHITECTURE.md` §5.

**Track:** 1 — MemoryAgent · **Model:** Qwen3 on Qwen Cloud (Model Studio) · **Backend:** Alibaba Cloud

---

### What it does
The same agent answers a recurring, high-stakes CMO question — *"ROAS dropped this
week; where should the budget go?"* — across five sessions, and its decision accuracy
**climbs** while a memoryless baseline stays flat. It has three memory stores
(preferences like "never cut the brand campaign below its floor"; outcomes of past
recommendations; episodic run summaries), retrieves the relevant few under a hard
1,500-token budget, and **forgets** on a half-life so stale lessons don't mislead it.

### How we built it
- **Qwen Cloud** for reasoning (single shared `llm.py` client, OpenAI-compatible).
- **Memory stores** in SQLite: `preference | outcome | episode`, each with confidence,
  decayed outcome-weight, and status.
- **Forgetting policy** (pure, unit-tested): outcome half-life decay; contradiction
  demotion (a new outcome that opposes an old belief demotes it); preference staleness
  for re-confirmation.
- **Retriever:** score = relevance × recency × outcome-weight, embeddings-or-lexical,
  context capped at ~1,500 tokens (truncate lowest-score first).
- **MemoryAgent wrapper:** injects recall pre-decide, writes an outcome memory
  post-decision; a 5-session runner persists memory between runs.
- Everything also runs in a deterministic **`--mock`** mode (no key) so judges can
  reproduce it offline; **162 automated tests**.

### Result (the metric that wins the track)
- **Accuracy-over-sessions (mechanism, deterministic):** **4.8 → 10.8 / 11 over 5
  sessions (+6.0)**; baseline flat at 4.8; **tokens-per-decision stay flat** (retrieval
  keeps context bounded — it never grows with history).
- **On live Qwen**, a lone model is noisier — but composed with a specialist society,
  memory drives the best result in our whole benchmark: **86.4%** averaged over 5
  distinct CMO questions (vs 68% for the society alone). Memory's biggest win is
  *fixing a recurring mistake the base system makes on its own.*
- **Money-shot:** a per-decision trace — *recall → baseline instinct → memory
  correction → outcome learned* — showing the brand-floor trap flip from a wrong budget
  cut to "hold" once the correction is remembered.

### Honesty
We report the mechanism (mock, clean climb) and the live result (noisier) **separately,
never substituted** — and show that memory pays off most when its recalled rules are
*enforced* by structure, not merely recalled by a lone model.

### Judging-criteria fit
- **Innovation (30%):** a real, unit-tested *forgetting* policy (decay + contradiction
  demotion + staleness) — the part most memory entries skip.
- **Technical depth (30%):** bounded-context retrieval, deterministic mock mode, 151
  tests, one shared foundation reused across tracks.
- **Impact (25%):** a genuine, high-frequency CMO decision; accuracy compounds over time.
- **Presentation (15%):** live UI with plain-English per-session traces + a "run it live" button.

### Links
- Repo: ____  · Demo video (<3 min): ____ · Architecture diagram: `submissions/diagrams/track1.*`
- Alibaba Cloud deployment proof: ____ (Model Studio call in `config.py` / `llm.py`; backend on ECS/FC)
