# Showcase UI — one problem, three architectures

A Next.js (App Router) frontend + FastAPI backend that drives the three tracks
live. Everything runs in **mock mode** — no API key, no network.

## Quick start (from the `hackathon/` dir)

```bash
bash run_ui.sh          # installs deps, starts API :8000 + UI :3000
# open http://localhost:3000
```

Or run the two halves manually:

```bash
# backend
pip install -r api/requirements.txt
uvicorn api.main:app --reload --port 8000

# frontend (separate terminal)
cd web && npm install && npm run dev
```

Point the frontend at a non-default backend by setting `NEXT_PUBLIC_API_BASE`
in `web/.env.local` (see `.env.local.example`).

## Pages

- **Overview** — the comparison bench: headline deltas, a totals bar chart, the
  memory curve, and a per-scenario baseline-vs-society table.
- **Memory (Track 1)** — run N sessions; watch the accuracy curve climb and the
  trap scores flip red→green across the session matrix.
- **Society (Track 3)** — pick a scenario; see the Analyst / Forecaster / Risk
  cards (claim + evidence + confidence), the Risk veto, resolved conflicts, and
  the Coordinator ruling.
- **Autopilot (Track 4)** — pick a scenario, inject a fault (api500/timeout),
  choose a gate response (auto/approve/adjust/reject/expire), and watch the
  pipeline stepper end in a safe state (`completed` / `rolled_back` / `held` /
  `failed_safe` …).

## Backend endpoints (FastAPI, `api/main.py`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | provider + models |
| GET | `/api/scenarios` | the 10 scenarios + expected answers |
| GET | `/api/overview` | bench summary (cached; `?refresh=true`) |
| GET | `/api/baseline` | mock-heuristic per-scenario results |
| POST | `/api/track1/run` | `{sessions}` → memory curve + per-session detail |
| GET | `/api/track3/all` | society over all 10 |
| GET | `/api/track3/{sid}` | society decision + full debate transcript |
| POST | `/api/track4/run` | `{scenario, fault, gate}` → pipeline result |

The backend is a thin JSON wrapper over the existing track modules — it adds no
logic, so the UI shows exactly what the CLI/tests produce.

## Live mode (real Qwen on Qwen Cloud)

Every page defaults to **mock** (free, instant). When a DASHSCOPE_API_KEY is present
(`/api/health` → `live_available: true`), each interactive page exposes an
explicit, per-run **live** action that calls real Qwen on Qwen Cloud:

- **Society** — “⚡ Run live on S## (real Qwen)”: the Analyst and Forecaster
  become real LLM tool-loops (the Risk veto + Coordinator stay coded policy).
  Shows real tokens + latency; specialist cards show the model's own reasoning
  and the tools it actually called.
- **Autopilot** — a mock/**live** “diagnosis brain” toggle in the controls.
- **Overview** — “⚡ Run live baseline (10 Qwen Cloud calls)” compares live single-
  agent Qwen against the mock baseline, per scenario.
- **Memory** — a mock/**live** toggle (warned: live = sessions×10 model calls).

Live is always an explicit click, never automatic — so it never spends tokens by
surprise. The mechanism/thesis is identical in mock; live exists to show real
model numbers (and honest variability).

## Notes

- No chart library: the bar/line charts are hand-rolled SVG (theme-aware).
- The core Python package keeps its `openai`/`pytest`/`matplotlib`-only deps
  (PRD §4); FastAPI/uvicorn live only under `api/`, `boto3` only for live SigV4.
