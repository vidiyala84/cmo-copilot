# Submission — Track 4: Autopilot Agent

**Tagline:** Nobody asked the agent anything — an alert fires and it carries a marketing
budget decision all the way to a sandboxed execution, pausing only at a human gate,
with auto-rollback and rehearsed failure handling.

**Track:** 4 — Autopilot Agent · **Model:** Qwen3 on Qwen Cloud (Model Studio) · **Backend:** Alibaba Cloud

---

### What it does
A ROAS-drop alert (ambiguous by design) triggers an end-to-end workflow:
**triage → diagnose → propose → human gate → sandbox execute → monitor → auto-rollback →
closing report.** Trivial dips are filtered at triage; the human approves/adjusts/rejects
(or the plan expires); execution is idempotent and logged; a 14-day (compressed) monitor
auto-reverses the move if it breaches a guardrail — and an injected API failure is caught,
retried, rolled back, and reported as `failed_safe`.

### How we built it
- **Pipeline orchestrator** with a cheap triage filter, a Qwen-Cloud diagnosis brain
  (the Track 3 society is pluggable as the diagnoser), constraint-validated proposals
  with up to 2 replans, a **human approval gate** (interactive + `--auto-approve`; a
  Slack-webhook stub with a documented swap point; plan expiry), a **sandbox executor**
  with an idempotent run-manifest ledger, a **monitor** that simulates outcomes and
  **auto-rolls-back** on a guardrail breach, and **failure injection** (`api500` / `timeout`).
- Every number in the closing report traces to a tool-call ID; deterministic **`--mock`**
  mode; **162 tests**.

### Result (the metric that wins the track)
- **Completion / safe-failure / zero-unapproved-execution:**
  - **All 10 scenarios end in a safe terminal state**; 5 execute, 1 auto-rolls-back.
  - The tracking-outage trap **never moves budget** (routes to fix-tracking).
  - **Fault injection → `failed_safe`**: retry → partial rollback → human notification —
    never a silent half-execution.
  - **Zero executions without an approval record** in the ledger.
- **Money-shot:** the rehearsed failure — inject `api500` mid-execution and watch the
  pipeline retry, back out, notify, and exit `failed_safe`, with a full audit trail.

### Honesty
The diagnosis is only as good as the brain behind it, so the UI lets you toggle the
mock vs. live-society diagnoser and shows the exact pipeline steps, the approval record,
and every tool call for each run.

### Judging-criteria fit
- **Innovation (30%):** production-readiness details judges reward — ambiguity handling,
  a real human gate with expiry, idempotent execution, rehearsed failure + rollback.
- **Technical depth (30%):** a full state-machine pipeline, fault injection, guardrail
  monitor, run-manifest ledger, audit trail; clean, tested code.
- **Impact (25%):** closes the loop on a real business workflow unattended — the exact
  shape of a production execution gateway.
- **Presentation (15%):** live UI visualizes the pipeline as a stepper with plain-English
  notes; run any scenario, inject a fault, choose the gate outcome.

### Links
- Repo: ____ · Demo video (<3 min): ____ · Architecture diagram: `submissions/diagrams/track4.*`
- Alibaba Cloud deployment proof: ____ (Model Studio diagnosis via `llm.py`; backend on ECS/FC)
