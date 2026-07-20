# Devpost submission — paste-ready content

Fill the form top to bottom from here. The long "About the project" is below;
copy it straight into the Markdown editor.

---

## About the project  (paste this whole block into the Markdown editor)

## 💡 Inspiration

Every week a marketing leader faces the same question: **"ROAS moved — what do I do with
the budget?"** And the intuitive answer is usually *wrong*. Conversions crashed? It might be
a broken tracking pixel, not a real drop — moving budget makes it worse. Everything's down at
once? Probably seasonality — hold. The worst performer is the brand campaign? Don't touch it.

I didn't want to build a demo that looks smart on the happy path. I wanted to find out what
it actually takes to make an AI agent **reliable** on decisions where the obvious move is a
trap — so I built a controlled experiment.

## 🎯 What it does

**CMO Copilot is an AI copilot for marketing budgets** that turns a fuzzy CMO question into a reliable, auditable
recommendation over a real ad account (~300 campaigns, $1.2M/month):

- A **6-agent Qwen society** — Analyst, Forecaster, Risk Officer, Portfolio Planner, Growth
  Lead, Coordinator — diagnoses the account, debates under a structured protocol, vetoes a bad
  move, or assembles a multi-item plan.
- A **memory that learns which of the society's own calls to override** — from experience, not
  from rules I typed in. When a decision backfires, it learns a *structured gate* from the
  outcome, keeps only the gates its own history proves actually **matter**, and enforces them
  deterministically.

I measured everything on a **100-question benchmark** I generate with deterministic Python —
no model in the generation — where every correct answer is *proven present in the data* before
it counts.

**The result: 27% → 100% on the same benchmark, and it holds.**

## 🧪 The experiment — and the honest result

Seven architectures, the identical 100 questions, live on Qwen Cloud:

| Approach | Overall | Simple | Traps | Plans |
|---|---|---|---|---|
| Just ask Qwen | 27% | 2% | 65% | 0% |
| + every rule in the prompt | 51% | 36% | **91%** | 0% |
| Single agent + tools | 57% | 80% | 48% | 27% |
| 6-agent society | 66% | 80% | **86%** | 100%\* |
| LLM planner | 71% | 95% | 32% | **100%** |
| Tool-derived (structured) | 76% | **100%** | 40% | **100%** |
| **Compose → gated planner** | **100%** | **100%** | **100%** | **100%** |

**No single approach wins all three tiers, and the failure modes are opposite.** Rules and the
veto crack the **traps** (knowing when to *hold*). Tools and planning crack the **fixes and
plans** (knowing *what to do*). Each has a hole in the other's strength. Compose them — a
planner behind a risk/trap gate — and it solves everything. But that **hand-codes** the gates,
which raised the real question: *can a memory **learn** them?*

## 🏗️ How I built it

- **Qwen on Alibaba Cloud Model Studio**, used deliberately: `qwen-plus` for orchestration,
  `qwen-flash` for cheap sub-tasks, `qwen-max` for synthesis, via an OpenAI-compatible
  tool-calling loop, with `text-embedding-v3` powering the memory's retrieval.
- A **Model Context Protocol (MCP) server** (`cmo-copilot`, FastMCP) exposing the whole
  tool belt — so any MCP client, including a Qwen agent via a bridge, can diagnose and plan
  against the account with the system's audited, group-rollup, O(1)-context tools.
- **The learned memory**: it observes raw features (funnel drops, elasticity, roas spread,
  flags, opportunity lift) and fits a **decision tree** on its accumulated outcome history each
  session. The tree *discovers the thresholds itself* — e.g. it learned `cvr_drop > 0.53 →
  fix tracking`, `0.15–0.53 → fix targeting`. A gate only fires if history shows it *mattered*
  (the base was really getting those cases wrong), and enforcement is a deterministic match —
  not an LLM re-reading its own note.
- **Engineering**: ~300 campaigns rolled up to 5 groups for O(1) context (measured — dumping
  the account blows the 32k window at ~500–1,000 campaigns), a deterministic offline mode for
  reproducible CI, fail-closed constraints, and **170 automated tests**.

## 🧗 Challenges I ran into

- **The obvious memory doesn't work.** Prose memory (the model writing itself lessons) *discovers
  the right gates but oscillates and degrades* — 30→44→46→32→31% on the traps over 5 sessions.
  Outcome-based feedback made it steadier but still didn't converge. I report both negatives in
  full — the instability is intrinsic to a fuzzy rule an LLM re-applies by hand.
- **Overfitting.** My first "structured gate" hand-set the thresholds. I caught it — that's *us*
  learning, not the memory — and replaced it with a decision tree that learns the boundaries.
- **The hold-vs-plan tension is real** and had to be *composed*, not chosen.

## 🏆 Accomplishments I'm proud of

- A memory that **learns and stays stable**: Society + Memory 74% → 100% over four sessions, and
  it holds — where every prose variant oscillated. The tree it learns on a **live Qwen base** is
  *identical* to the one on a deterministic base, because it learns the task's structure, not the
  base's noise. And enforcement costs **zero** LLM calls, so it gets *cheaper* as it learns.
- I reported every negative result instead of hiding it.

## 📚 What I learned

A smart model is table stakes. **Reliability** comes from a specialist society that *reasons*
and a memory that **learns from experience which of its calls to override** — validated against
its own history, enforced deterministically. Better prompts and better feedback made the model
*steadier*; only structure made it *right*.

## 🚀 What's next for CMO Copilot

Wire the learned-gate memory to more of the live account; extend the pattern (learn a gate,
validate it mattered, enforce it) to any repeated business decision with a feedback signal — the
AI copilot for marketing budget decisions.

---

## Built with  (tags — paste comma-separated)

`qwen` · `qwen-cloud` · `alibaba-cloud` · `model-studio` · `dashscope` · `mcp` · `fastmcp` ·
`python` · `scikit-learn` · `decision-trees` · `embeddings` · `openai-python` · `fastapi` ·
`sqlite` · `pandas` · `docker` · `next.js`

## "Try it out" links

- **Code:** https://github.com/vidiyala84/cmo-copilot  ← **make PUBLIC before submitting**
- **Deployed backend (Alibaba Cloud):** __________  (from DEPLOY.md — paste the ECS/FC public URL)
- **Video:** __________  (record from `presentation.html` — see below)

## Video demo link  (required)

Record ~3 min from `presentation.html` (full-screen, arrow-key through the 12 slides), cutting
mid-way to a live browser tab of `benchmark_review.html` (scroll a couple of cards + the
campaign drill-down). Upload to YouTube/Vimeo, paste the URL.

## Project Media — image gallery (3:2, ≤5MB, up to 15)

Good screenshots to upload: (1) a `presentation.html` slide with the 7-approach bar chart,
(2) the Society+Memory 74→100 line chart, (3) the learned decision tree slide, (4) a
`benchmark_review.html` card with the campaign drill-down, (5) the terminal output of
`python -m tracks.track1.memory_gates --sessions 4 --base society`.

## Additional info (for judges)

- **Submitter type:** Individual
- **Organization name:** *(optional — your company, or leave blank)*
- **Country of residence:** *answer truthfully.* ⚠️ As an individual submitter you must reside in an
  **eligible** region — the rules exclude several regions **including India**. State your real
  country of residence; do not misrepresent it.
- **Newly built or previously existing project:** Newly built

---

## More "Additional info" fields (paste / select)

- **What date did you start this project? (MM-DD-YY):** `07-12-26`
  *(when this hackathon codebase — benchmark, society, memory, MCP — was first built; adjust to your actual first-commit date).*
- **Started/existed before May 26 — what you updated:** **Leave blank.** The project was built new during the submission period (after May 26); all code is original to this hackathon.
- **Which Track:** **MemoryAgent** *(the learned-gate memory is the centerpiece; Agent Society is the secondary angle).*
- **Code repository URL (for judging):** `https://github.com/vidiyala84/cmo-copilot`  ← **make PUBLIC first (with the MIT LICENSE visible)**
- **URL to code file showing Alibaba Cloud service usage:**
  `https://github.com/vidiyala84/cmo-copilot/blob/main/cmo/llm.py`
  *(the Qwen client against Model Studio / DashScope; `config.py` has the dashscope base URL + models; `DEPLOY.md` documents the Alibaba Cloud deploy).*
- **Architecture Diagram (upload):** screenshot the **"System / deployment topology"** diagram at the top of `ARCHITECTURE.md` (renders on GitHub) → save PNG → upload.
- **Screenshot proof of Alibaba Cloud deployment (upload):** ⚠️ **requires the backend actually deployed** — follow `DEPLOY.md` (ECS ≈ 10 min), then screenshot the running service (`/api/health` JSON in the browser **and** the Alibaba Cloud ECS/Function-Compute console). Hard requirement.
- **Blog/Social post URL (optional, Blog Prize):** blank unless you published one.
- **Which AI tools did you leverage:**
  > The product runs on **Qwen** (`qwen-plus` / `qwen-flash` / `qwen-max`) via **Alibaba Cloud Model Studio**, with `text-embedding-v3` for the memory's retrieval and an **MCP server** exposing the tool belt. Development was assisted by Claude Code.
- **Level of learning derived (dropdown):** select the **highest / "Significant"** — a genuine multi-experiment research arc (three memory designs, honest negative results).
- **Eligibility checkboxes:** check **only if true**. ⚠️ *"from an eligible jurisdiction"* — the rules exclude several regions **including India**; the registered submitter and teammates must qualify. Answer honestly.

## Testing Instructions (paste — and this is a *strength*: no credentials needed)

No credentials required — everything runs offline, deterministically:

```
pip install -r requirements.txt
pytest -q                                                   # 170 tests, all pass
python -m cmo.harness --agent mock                              # canary = 4.8/11
python -m cmo.benchmark --mock                                  # the 100-question benchmark
python -m tracks.track1.memory_gates --sessions 4 --base society   # Society + learned Memory -> 100%
python -m cmo.build_review                                      # -> benchmark_review.html (all 100, reviewable)
python -m cmo.mcp_server                                        # the MCP server (stdio)
```

For the LIVE Qwen Cloud numbers, put `DASHSCOPE_API_KEY` in `.env` (`LLM_PROVIDER=dashscope`), then:
```
python scripts/check_live.py && python -m cmo.bench_live                # the 7-approach comparison, live
```
