"""Live driver — run every approach over the 100-question benchmark on Qwen Cloud.

This is the reconstructed head-to-head: the same 100 generated questions (data +
questions authored deterministically, NOT by the model), answered by each
architecture, scored on the same rubric, broken down by difficulty tier. The only
thing that changes between rows is HOW the answer is produced.

Approaches:
  mock         offline naive heuristic — the strawman ("everything is a budget move")
  structured   offline tool-derived rules engine — strong on funnel/plans, blind to traps
  direct       live Qwen, no tools, no rules ("just ask the model")
  direct_rules live Qwen, every business rule handed to it in the prompt
  qwen         live Qwen + the tool belt (the single-agent baseline)
  society      live 4-agent society (Analyst/Forecaster/Risk/Coordinator)

Cost control (society is ~15–20k tokens/decision): use --limit and --difficulty,
or --approaches to pick a subset. A full 6-approach × 100-question run is ~2–3M
tokens — well inside the 70M free tier, but budget ~20 min for the society row.

    python bench_live.py --approaches mock,structured                 # offline sanity
    python bench_live.py --approaches qwen --limit 5                  # live smoke test
    python bench_live.py --difficulty complex --approaches structured,qwen,society
    python bench_live.py                                              # full run, all approaches
"""
import argparse
import json
import time

from cmo.benchmark import generate, run, summarize, validate
from cmo.config import RUNS_DIR
from cmo.datagen import generate_base

DEFAULT = ["mock", "structured", "gated", "direct", "direct_rules", "qwen", "society", "planner_llm"]
ORDER = {n: i for i, n in enumerate(DEFAULT)}
LIVE = {"direct", "direct_rules", "qwen", "society", "planner_llm"}   # gated is deterministic/offline


def build(name):
    if name == "mock":
        from cmo.agents import MockHeuristicAgent
        return MockHeuristicAgent()
    if name == "structured":
        from cmo.agents import StructuredAgent
        return StructuredAgent()
    if name == "gated":
        from cmo.agents import GatedPlannerAgent
        return GatedPlannerAgent()
    if name == "direct":
        from cmo.agents import DirectQwenAgent
        return DirectQwenAgent(mock=False, with_rules=False)
    if name == "direct_rules":
        from cmo.agents import DirectQwenAgent
        return DirectQwenAgent(mock=False, with_rules=True)
    if name == "qwen":
        from cmo.agents import QwenBaselineAgent
        return QwenBaselineAgent()
    if name == "planner_llm":
        from cmo.agents import PlannerLLMAgent
        return PlannerLLMAgent()
    if name == "society":
        from tracks.track3.society import SocietyAgent
        return SocietyAgent(mock=False)
    raise ValueError(f"unknown approach {name}")


def _markdown(rows):
    lines = ["# Live benchmark — one problem, 100 questions, N architectures", "",
             "_Data + questions generated deterministically (seed 42); every approach "
             "answers the same 100. Score is % of max. Live rows run on Qwen Cloud._", "",
             "| Approach | Overall | Simple (40) | Medium (40) | Complex (20) |",
             "|---|---|---|---|---|"]
    for r in rows:
        b = r["summary"]["by_difficulty"]
        lines.append(f"| {r['name']} | **{r['summary']['pct']}%** | {b['simple']['pct']}% | "
                     f"{b['medium']['pct']}% | {b['complex']['pct']}% |")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--approaches", default=",".join(DEFAULT),
                    help="comma-separated subset of: " + ", ".join(DEFAULT))
    ap.add_argument("--difficulty", choices=["simple", "medium", "complex"])
    ap.add_argument("--limit", type=int, help="cap questions (cost control)")
    args = ap.parse_args()

    approaches = [a.strip() for a in args.approaches.split(",") if a.strip()]
    approaches.sort(key=lambda n: ORDER.get(n, 99))

    base = generate_base()
    scenarios = generate()
    if args.difficulty:
        scenarios = [s for s in scenarios if s["difficulty"] == args.difficulty]
    if args.limit:
        scenarios = scenarios[:args.limit]

    bad = [s["id"] for s in scenarios if not validate(s, base)]
    print(f"benchmark: {len(scenarios)} questions, {len(scenarios)-len(bad)} verified"
          + (f"  ✗ {bad}" if bad else ""))
    if any(a in LIVE for a in approaches):
        print(f"live approaches: {[a for a in approaches if a in LIVE]} — spends Qwen Cloud tokens\n")

    RUNS_DIR.mkdir(exist_ok=True)
    rows = []
    for name in approaches:
        t0 = time.time()
        res = run(build(name), scenarios, base)
        s = summarize(res)
        b = s["by_difficulty"]
        print(f"{name:13} {s['pct']:5}%   simple {b['simple']['pct']:5}%  "
              f"medium {b['medium']['pct']:5}%  complex {b['complex']['pct']:5}%   "
              f"({round(time.time()-t0)}s)", flush=True)
        rows.append({"name": name, "summary": s, "results": res})
        # persist after EACH approach so a long run never loses completed work
        (RUNS_DIR / "benchmark_live.json").write_text(json.dumps(
            {"n_questions": len(scenarios), "approaches": rows}, indent=2))
        (RUNS_DIR / "benchmark_comparison.md").write_text(_markdown(rows))
    print(f"\nsaved -> {RUNS_DIR/'benchmark_live.json'} and benchmark_comparison.md")


if __name__ == "__main__":
    main()
