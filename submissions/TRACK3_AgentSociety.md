# Submission — Track 3: Agent Society

**Tagline:** A "marketing team in a box" — now **six** specialist Qwen agents (Analyst,
Forecaster, Risk Officer, **Portfolio Planner**, **Growth Lead**, Coordinator) that
argue under a structured protocol and reach a better, safer answer than one generalist,
with the debate transcript as proof.

> **Headline result (100-question benchmark, real Qwen on Qwen Cloud):** the society
> scores **66%** live — strongest of the pure-LLM approaches on the traps (86%, via its
> Risk veto), and the two new specialists give it the **multi-item plans** it never had
> (complex tier 0% → 100%). Its one blind spot (funnel diagnosis) is closed by a
> **learned memory** that gates the calls it gets wrong: **Society + Memory converges to
> 100% over four sessions and holds.** Full story & numbers: `../docs/SUBMISSION.md` §1–4;
> diagrams in `../docs/ARCHITECTURE.md` §2 & §5.

**Track:** 3 — Agent Society · **Model:** Qwen3 on Qwen Cloud (Model Studio) · **Backend:** Alibaba Cloud

---

### What it does
Given the same CMO budget question, four roles collaborate: a **Performance Analyst**
diagnoses *why* ROAS moved, a **Forecaster** proposes the most aggressive profitable
move, a **Risk & Brand Officer** validates it against hard business rules with an
**absolute veto**, and a **Coordinator** runs a bounded debate and rules with an
explicit, coded policy. Every decision emits a full transcript showing the conflict and
how it was resolved.

### How we built it
- **Structured negotiation protocol** (not free-form chat): every agent submits
  `claim + evidence + confidence`; a conflict detector triggers ≤2 rebuttal rounds; the
  Coordinator rules by **evidence quality > confidence > conservative default**, and a
  Risk veto is absolute.
- **Roles on Qwen Cloud:** Analyst + Forecaster reason live; the Risk Officer's
  constraint check is a *deterministic validator* (`propose_reallocation`) — a coded
  gate, not a guess; the Coordinator is a coded synthesis policy.
- Shared foundation (same data/tools/scoring as the other tracks); deterministic
  **`--mock`** mode; transcripts written per decision; **162 tests**.

### Result (the metric that wins the track)
- **Accuracy delta vs baseline:** **9.0 / 11 vs 4.8 single-agent baseline (+4.2)** in the
  deterministic mode; **68% vs ~48% averaged over 5 CMO questions on live Qwen.** It
  solves all three trap cases a single agent walks into.
- **Cost of the delta (measured, reported even if unflattering):** ~15–20k tokens and
  ~10s per decision — about **3–5× a single agent**. The pitch is *accuracy per dollar
  on hard cases*, not raw efficiency.
- **Money-shot:** the brand-floor transcript — the Forecaster wants to cut the brand
  campaign; the **Risk Officer vetoes** ("would breach the $2,000/mo brand floor"); the
  Coordinator holds. Every figure in every claim traces to a tool call.

### Honesty
Live, the society's edge over a *well-briefed single prompt* is real but modest (68% vs
64.8%) — the win is concentrated in the trap cases where constraints must be enforced,
not merely stated. We show that gap explicitly.

### Judging-criteria fit
- **Innovation (30%):** a coded ruling policy + absolute-veto protocol, and a measured
  accuracy delta (most entries claim it; we prove it, and report the token cost).
- **Technical depth (30%):** deterministic conflict-resolution logic (table-tested),
  tool-grounded evidence, per-decision transcripts, multi-agent orchestration.
- **Impact (25%):** the "tracking outage disguised as decay" and brand-floor cases are
  real, expensive CMO mistakes the society avoids.
- **Presentation (15%):** live UI renders each specialist's claim + evidence + the
  resolved conflict; click any scenario to watch a real Qwen debate.

### Links
- Repo: ____ · Demo video (<3 min): ____ · Architecture diagram: `submissions/diagrams/track3.*`
- Alibaba Cloud deployment proof: ____ (Model Studio calls in `track3/society.py` via `llm.py`)
