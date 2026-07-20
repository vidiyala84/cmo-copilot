# CMO Copilot

**An AI copilot for marketing budgets** — a 6-agent Qwen society whose own
mistakes a *learned memory* gates, over a realistic ad account (~300 campaigns,
$1.2M/month). Built for the Qwen Cloud hackathon on **Qwen (Alibaba Cloud Model
Studio)** with a **Model Context Protocol** server.

> **Headline result: 27% → 100%** on a 100-question CMO benchmark generated
> deterministically in Python (no model in the generation; every correct answer
> is *proven present in the data* before it counts).

The hard part isn't a smart model — it's **reliability** on decisions where the
obvious move is a trap (a conversion drop that's a broken pixel, not a real
decline). A planner behind a risk/trap gate solves every tier; a memory that
**learns which of the society's own calls to override** — a decision tree fit on
its own outcome history, kept only when history proves it *mattered*, enforced
deterministically — gets there without the gates being hand-coded.

## Layout

```
cmo/       the engine: config, datagen, scenarios, portfolio, modeling,
           tools, policy, llm (Qwen client), agents, harness, benchmark,
           multi_item, build_review, mcp_server
tracks/    track1 (learned-gate memory) · track3 (agent society) · track4 (autopilot)
api/       FastAPI backend (landing page + JSON API) — the deployable surface
scripts/   check_live.py, export_data.py (standalone utilities)
docs/      SUBMISSION · ARCHITECTURE · DEPLOY · DEVPOST · DEMO
web/        optional Next.js dev UI (not required to run or deploy)
tests/     170 offline tests
```

## Quickstart (offline, no key)

```bash
pip install -r requirements.txt
pytest -q                                             # 170 tests
python -m cmo.harness --agent mock                    # canary = 4.8/11
python -m cmo.benchmark --mock                        # the 100-question benchmark
python -m tracks.track1.memory_gates --sessions 4 --base society   # memory -> 100%
python -m cmo.build_review                            # -> benchmark_review.html
python -m cmo.mcp_server                              # the MCP server (stdio)
```

## Live on Qwen Cloud

Put your key in `.env` (`DASHSCOPE_API_KEY=...`, `LLM_PROVIDER=dashscope` — see
`.env.example`), then:

```bash
python scripts/check_live.py        # one-shot connectivity check
python -m cmo.bench_live            # the 7-approach comparison, live on Qwen
```

Endpoint defaults to the international Model Studio compatible-mode URL; set
`QWEN_BASE_URL` for CN-region accounts. Model ids default to `qwen-plus` /
`qwen-flash` / `qwen-max` — verify the exact strings in your console.

## Deploy

`docs/DEPLOY.md` — a container on Alibaba Cloud (ECS / Function Compute / SAE).
`docker build -t cmo-copilot . && docker run -p 8000:8000 -e DASHSCOPE_API_KEY=sk-... cmo-copilot`,
then open `/` for the landing page and `/api/health` for status.

## The story

`docs/SUBMISSION.md` is the full write-up (the seven-architecture experiment, the
honest negative results, and the learned-gate memory). `docs/ARCHITECTURE.md` has
the system topology and the society+memory loop. MIT licensed.
