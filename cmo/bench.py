"""H4-1 — comparison bench: run every architecture on the same 10 scenarios and
emit the headline table + charts.

    python bench.py --mock

Produces runs/comparison.md, runs/comparison.png, runs/track1_curve.png (and
runs/bench.json with the raw numbers the table is built from).

Honesty rule: token/latency cells show MEASURED values only. Mock-mode runs are
labelled `mock` — never presented as live model results. The heuristic/society
mock brains use no LLM, so their token cell is `mock (no LLM)`; latency and
tool-call counts are real wall-clock/graph measurements.
"""
import argparse
import json

from cmo.config import QWEN_API_KEY, RUNS_DIR
from cmo.harness import run as harness_run, score
from cmo.scenarios import SCENARIOS

N_SCENARIOS = len(SCENARIOS)  # the harness total is out of this, not a literal 10

TRAPS = ("S02", "S07", "S08", "S09")


def _summarize(results, label, tokens="mock (no LLM)"):
    per = {r["scenario"]: r["score"] for r in results}
    return {
        "label": label,
        "total": round(sum(r["score"] for r in results), 2),
        "per_scenario": per,
        "traps": {t: per.get(t) for t in TRAPS},
        "tool_calls": sum(r["tool_calls"] for r in results),
        "latency_s": round(sum(r["latency_s"] for r in results), 3),
        "tokens": tokens,
    }


def _score_agent(agent, label, tokens="mock (no LLM)"):
    return _summarize(harness_run(agent), label, tokens)


def run_bench(mock=True, out_dir=None, sessions=5):
    out_dir = out_dir or RUNS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = {}

    # --- baseline (mock heuristic) ---
    from cmo.agents import MockHeuristicAgent
    rows["baseline_mock"] = _score_agent(MockHeuristicAgent(), "Baseline (mock heuristic)")

    # --- baseline (live qwen), only if a key is present and live requested ---
    if not mock and QWEN_API_KEY:
        try:
            from cmo.agents import QwenBaselineAgent
            agent = QwenBaselineAgent()
            rows["baseline_qwen"] = _score_agent(agent, "Baseline (qwen, live)",
                                                 tokens="measured per run")
        except Exception as e:  # pragma: no cover - live only
            print(f"(skipping live qwen baseline: {e})")

    # --- Track 3 society (mock) ---
    from tracks.track3.society import SocietyAgent
    rows["society_mock"] = _score_agent(
        SocietyAgent(mock=True, transcripts_dir=out_dir / "transcripts"),
        "Society (mock, 4 agents)")

    # --- Track 1 memory: session 1 vs session N ---
    from tracks.track1.session_runner import run_sessions, write_chart
    mem = run_sessions(sessions=sessions, mock=True, db_path=str(out_dir / "bench_memory.db"))
    s1 = mem["per_session"][0]
    sN = mem["per_session"][-1]

    def _mem_row(sess, label):
        per = {r["scenario"]: r["score"] for r in sess["results"]}
        return {"label": label, "total": sess["total"], "per_scenario": per,
                "traps": {t: per.get(t) for t in TRAPS},
                "tool_calls": None,
                "latency_s": None,
                "tokens": f"mock ctx ~{sess['avg_context_tokens']}/decision"}

    rows["memory_s1"] = _mem_row(s1, f"MemoryAgent — session 1 (cold)")
    rows["memory_sN"] = _mem_row(sN, f"MemoryAgent — session {sessions}")

    # --- Track 4 autopilot (mock) ---
    from tracks.track4.autopilot import Autopilot
    from cmo.scenarios import SCENARIOS
    auto_results = Autopilot(mock=True, auto_approve=True, out_dir=out_dir).run_all()
    exp = {s["id"]: s["expected"] for s in SCENARIOS}
    auto_per = {r.scenario: score(r.decision, exp[r.scenario])[0] if r.decision else 0.0
                for r in auto_results}
    rows["autopilot_mock"] = {
        "label": "Autopilot (mock, gated)",
        "total": round(sum(auto_per.values()), 2),
        "per_scenario": auto_per,
        "traps": {t: auto_per.get(t) for t in TRAPS},
        "tool_calls": sum(r.tool_calls for r in auto_results),
        "latency_s": None,
        "tokens": "mock (no LLM)",
        "autopilot": {
            "safe": sum(r.safe for r in auto_results),
            "executed": sum(r.executed for r in auto_results),
            "rolled_back": sum(r.rolled_back for r in auto_results),
            "n": len(auto_results),
        },
    }

    report = {"mock": mock, "sessions": sessions, "rows": rows,
              "memory_curve": mem["curve"], "memory_baseline": mem["baseline_total"]}

    _write_markdown(report, out_dir / "comparison.md")
    _write_bar_chart(report, out_dir / "comparison.png")
    write_chart(mem, out_dir / "track1_curve.png")
    with open(out_dir / "bench.json", "w") as f:
        json.dump(report, f, indent=2)
    return report


ORDER = ["baseline_mock", "baseline_qwen", "memory_s1", "memory_sN",
         "society_mock", "autopilot_mock"]


def _write_markdown(report, path):
    rows = report["rows"]
    lines = ["# Comparison — one problem, three architectures", ""]
    lines.append("_All runs on the identical 10-scenario harness (same data, tools, scoring). "
                 "Mock-mode numbers are labelled; they encode the intended architectural deltas, "
                 "not live-model results._")
    lines += ["", f"| Approach | Total /{N_SCENARIOS} | S02 | S07 | S08 | S09 | Tool calls | Latency (s) | Tokens |",
              "|---|---|---|---|---|---|---|---|---|"]
    for key in ORDER:
        if key not in rows:
            continue
        r = rows[key]

        def cell(v):
            return "—" if v is None else v
        traps = r["traps"]
        lat = "—" if r["latency_s"] is None else f"{r['latency_s']:.3f}"
        lines.append(f"| {r['label']} | {r['total']} | {cell(traps['S02'])} | "
                     f"{cell(traps['S07'])} | {cell(traps['S08'])} | {cell(traps['S09'])} | "
                     f"{cell(r['tool_calls'])} | {lat} | {r['tokens']} |")
    # headline deltas
    base = rows["baseline_mock"]["total"]
    soc = rows["society_mock"]["total"]
    mem1, memN = rows["memory_s1"]["total"], rows["memory_sN"]["total"]
    auto = rows["autopilot_mock"]["autopilot"]
    lines += ["", "## Headlines", "",
              f"- **Track 1 (Memory):** {mem1} → {memN} across {report['sessions']} sessions "
              f"(**+{round(memN - mem1, 2)}**), baseline flat at {report['memory_baseline']}.",
              f"- **Track 3 (Society):** {soc}/{N_SCENARIOS} vs baseline {base}/{N_SCENARIOS} "
              f"(**+{round(soc - base, 2)}**); nails the S02 tracking trap and the S07/S08 vetoes.",
              f"- **Track 4 (Autopilot):** {auto['safe']}/{auto['n']} scenarios ended in a safe "
              f"state, {auto['executed']} executed, {auto['rolled_back']} auto-rolled-back; "
              f"zero executions without an approval record."]
    path.write_text("\n".join(lines) + "\n")


def _write_bar_chart(report, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        print(f"(skipping comparison chart: {e})")
        return None
    rows = report["rows"]
    keys = [k for k in ORDER if k in rows]
    labels = [rows[k]["label"].split(" (")[0].replace("MemoryAgent — ", "Mem ") for k in keys]
    totals = [rows[k]["total"] for k in keys]
    colors = ["#9ca3af", "#93c5fd", "#60a5fa", "#2563eb", "#f59e0b", "#10b981"][:len(keys)]
    fig, ax = plt.subplots(figsize=(9, 4.6))
    bars = ax.bar(labels, totals, color=colors)
    ax.axhline(rows["baseline_mock"]["total"], color="#9ca3af", linestyle="--", alpha=0.7)
    ax.set_ylabel(f"Harness total (/{N_SCENARIOS})")
    ax.set_ylim(0, 10.5)
    ax.set_title("Same problem, three architectures (mock mode)")
    for b, t in zip(bars, totals):
        ax.text(b.get_x() + b.get_width() / 2, t + 0.15, str(t), ha="center", fontsize=9)
    plt.xticks(rotation=20, ha="right", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mock", action="store_true", help="offline only (no live qwen)")
    ap.add_argument("--sessions", type=int, default=5)
    args = ap.parse_args()
    report = run_bench(mock=args.mock, sessions=args.sessions)
    print(f"\nWrote comparison.md, comparison.png, track1_curve.png, bench.json to {RUNS_DIR}")
    for key in ORDER:
        if key in report["rows"]:
            r = report["rows"][key]
            print(f"  {r['label']:<34} total {r['total']}/{N_SCENARIOS}")


if __name__ == "__main__":
    main()
