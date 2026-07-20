# DEMO runbook — one problem, three architectures

Everything here runs **offline in mock mode** (no API key, no network). The
`--mock` numbers encode the intended architectural deltas; swap in a Qwen key
(`.env` — `DASHSCOPE_API_KEY`) for live figures.

Setup once:

```bash
pip install -r requirements.txt
python -m cmo.datagen            # writes data/base_campaigns.csv (deterministic, seed 42)
```

Canary (run any time — must always print **4.8**):

```bash
python -m cmo.harness --agent mock        # Baseline total: 4.8 / 11
```

---

## Demo 0 — the shared foundation (30s)

**Say:** "One marketing problem — 'ROAS dropped, where should budget go?' — with a
5-group (~300-campaign), 90-day dataset, a shared tool belt, and an 11-scenario
scorer. Several scenarios are traps. Every architecture is graded on this exact
rubric, so any delta is architectural, not data luck."

```bash
python -m cmo.harness --agent mock
```

**Money shot:** the baseline scores **4.8/11** and fails S07 (brand floor), S08
(learning phase), S09 (budget cap) — the headroom the tracks convert.

---

## Demo 1 — Track 1 MemoryAgent: "CMO Copilot remembers" (90s)

**Say:** "The same agent, run five sessions in a row, persisting memory between
runs. Session 1 is a cold start. After it, the user corrects it — 'never move
budget out of brand.' From then on it also learns from the outcomes of its own
past decisions."

```bash
python -m tracks.track1.session_runner --sessions 5 --agent mock
```

**Money shot:** the printed curve climbs **4.8 → 8.8 → 9.8 → 10.8 → 10.8** while the
baseline stays flat at 4.8; `runs/track1_curve.png` is the chart. Context stays
bounded (retrieval, not history-stuffing). Session 2 respects the brand
correction; sessions 3-4 change course on the patience/increase traps after
enough backfires — that's the forgetting/learning policy, not a lookup table.

---

## Demo 2 — Track 3 Society: "the marketing team in a box" (90s)

**Say:** "Four specialists — Analyst, Forecaster, Risk Officer, Coordinator —
argue under a structured protocol. The Forecaster always wants to move money; the
Analyst's diagnosis and the Risk Officer's veto rein it in. The transcript is the
demo."

```bash
python -m cmo.harness --agent society --mock
cat runs/transcripts/S07.json      # the brand-floor veto, resolved
```

**Money shot:** the society scores **9.0/11** (+4.2 over baseline), and every
decision's transcript shows at least one resolved conflict. S07/S08 are Risk
vetoes; S02 (tracking outage) is diagnosed as *fix tracking*, never a budget move.

---

## Demo 3 — Track 4 Autopilot: "alert to executed reallocation" (2min)

**Say:** "Nobody asked the agent anything. An alert fires; the pipeline triages,
diagnoses, proposes, pauses at the human gate, executes in a sandbox, monitors 14
compressed days, and rolls back if the guardrail trips."

```bash
python -m tracks.track4.autopilot --all --mock --auto-approve
```

**Money shot:** all 11 scenarios end in a **safe** state; trivial dips exit at
triage; S02 never moves budget; one scenario auto-rolls-back on a guardrail
breach; zero executions without an approval record (`runs/approvals.jsonl`).

Then the **rehearsed failure**:

```bash
python -m tracks.track4.autopilot --scenario S01 --mock --auto-approve --inject-fault api500
```

**Money shot:** the ad API 500s mid-execution → retry ×2 → partial rollback →
human notification → status **`failed_safe`**. Never a silent half-execution.
See `runs/track4_report_S01.md` for the full audit trail.

---

## Demo 4 — all three side by side (2min)

**Say:** "These aren't competing answers — they're layers. Memory makes any agent
smarter over time, the society is *how* a hard call gets made, the autopilot is
*what happens after*. One bench, same 11 scenarios."

```bash
python -m cmo.bench --mock
open runs/comparison.png            # or: cat runs/comparison.md
```

**Money shot:** the headline table — Baseline 4.8, Memory 4.8→10.8, Society 9.0,
Autopilot 11/11 safe — plus `runs/comparison.png` and `runs/track1_curve.png`.

---

## Going live (after the mock demo)

1. `cp .env.example .env`, set `LLM_PROVIDER=dashscope` + `DASHSCOPE_API_KEY`
   (your Qwen Cloud / Model Studio key).
2. Verify the exact Qwen model IDs + model access in your Model Studio console.
3. Drop `--mock`: `python -m cmo.harness --agent society`, `python -m cmo.bench`.
4. Live token/latency land in `runs/*.json`; nothing in the deck is hand-written.
