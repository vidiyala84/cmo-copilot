"""H1-3 — run the harness N times with persistent memory and chart the curve.

    python -m track1.session_runner --sessions 5 --agent mock

Each session: apply forgetting -> decide+score all 10 scenarios -> write
outcomes -> apply any scheduled user corrections. The memory agent's total
climbs; the baseline (single-shot heuristic, no memory) is a flat reference.
Emits runs/track1_curve.json and runs/track1_curve.png.
"""
import argparse
import json
import os

from cmo.config import RUNS_DIR
from cmo.datagen import generate_base
from cmo.harness import score
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv
from tracks.track1.memory_store import MemoryStore
from tracks.track1.retriever import Retriever, get_embedder
from tracks.track1.memory_agent import (MemoryAgent, MemoryAwareHeuristicAgent,
                                  MemoryAwareQwenAgent, apply_corrections, load_corrections)


def _baseline_total(base_rows):
    from cmo.agents import MockHeuristicAgent
    agent = MockHeuristicAgent()
    total = 0.0
    for sc in SCENARIOS:
        env = ScenarioEnv(base_rows, sc)
        total += score(agent.decide(env), sc["expected"])[0]
    return round(total, 2)


def run_sessions(sessions=5, mock=True, db_path=None, corrections_path=None, seed=42, base="heuristic"):
    base_rows = generate_base(seed)

    # fresh store per run for a deterministic, reproducible curve
    if db_path is None:
        RUNS_DIR.mkdir(exist_ok=True)
        db_path = str(RUNS_DIR / "memory.db")
    if db_path != ":memory:" and os.path.exists(db_path):
        os.remove(db_path)
    store = MemoryStore(db_path=db_path)

    retriever = Retriever(store, embedder=get_embedder(mock))
    if base == "society":
        from tracks.track1.memory_agent import MemorySocietyAgent
        base_agent = MemorySocietyAgent(mock=mock, transcripts_dir=RUNS_DIR / "transcripts_memsoc")
    elif mock:
        base_agent = MemoryAwareHeuristicAgent()
    else:
        base_agent = MemoryAwareQwenAgent()
    agent = MemoryAgent(base_agent, store, retriever)
    corrections = load_corrections(corrections_path)

    baseline_total = _baseline_total(base_rows)
    per_session = []
    for session in range(1, sessions + 1):
        forget_log = store.apply_forgetting(session)
        rows, ctx_tokens = [], []
        for sc in SCENARIOS:
            env = ScenarioEnv(base_rows, sc)
            try:
                decision = agent.decide(env, session)
            except Exception as e:  # a single crash scores 0, never kills the run
                decision = {"root_cause": "ERROR", "action": "ERROR", "source_campaign": None,
                            "target_campaign": None, "shift_pct": None, "rationale": str(e)[:200]}
                agent.last_trace = {}
            sc_score, notes = score(decision, sc["expected"])
            try:
                agent.record_outcome(env, sc, decision, sc_score, session)
            except Exception:
                agent.last_outcome = ""
            ctx_tokens.append(agent.last_context_tokens)
            rows.append({"scenario": sc["id"], "score": sc_score,
                         "root_cause": decision.get("root_cause"),
                         "action": decision.get("action"),
                         "context_tokens": agent.last_context_tokens, "notes": notes,
                         "steps": {**dict(agent.last_trace), "outcome_written": agent.last_outcome}})
        total = round(sum(r["score"] for r in rows), 2)
        n_applied = apply_corrections(store, corrections, after_session=session)
        per_session.append({
            "session": session, "total": total,
            "avg_context_tokens": round(sum(ctx_tokens) / len(ctx_tokens), 1),
            "corrections_applied": n_applied, "forgetting": forget_log, "results": rows,
        })

    curve = [s["total"] for s in per_session]
    return {
        "agent": agent.name, "mock": mock, "sessions": sessions,
        "baseline_total": baseline_total, "curve": curve,
        "session1_total": curve[0], "session_last_total": curve[-1],
        "gain": round(curve[-1] - curve[0], 2), "per_session": per_session,
    }


def write_chart(report, path):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:  # pragma: no cover
        print(f"(skipping chart, matplotlib unavailable: {e})")
        return None
    sessions = [s["session"] for s in report["per_session"]]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.plot(sessions, report["curve"], "-o", color="#2563eb", linewidth=2,
            label=f"MemoryAgent ({'mock' if report['mock'] else 'qwen'})")
    ax.axhline(report["baseline_total"], color="#9ca3af", linestyle="--",
               label=f"Baseline (no memory) = {report['baseline_total']}")
    ax.set_xlabel("Session")
    ax.set_ylabel("Harness total (/10)")
    ax.set_title("Track 1 — accuracy climbs as the agent remembers")
    ax.set_xticks(sessions)
    ax.set_ylim(0, 10.5)
    ax.legend(loc="lower right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=5)
    ap.add_argument("--agent", choices=["mock", "qwen"], default="mock")
    args = ap.parse_args()

    report = run_sessions(sessions=args.sessions, mock=(args.agent == "mock"))
    RUNS_DIR.mkdir(exist_ok=True)
    out_json = RUNS_DIR / "track1_curve.json"
    with open(out_json, "w") as f:
        json.dump(report, f, indent=2)
    png = write_chart(report, RUNS_DIR / "track1_curve.png")

    print(f"\nTrack 1 — MemoryAgent ({'mock' if report['mock'] else 'qwen'}), "
          f"{report['sessions']} sessions")
    print(f"Baseline (flat, no memory): {report['baseline_total']}/10")
    print(f"{'Session':<9}{'Total':<8}{'AvgCtxTok':<11}Corrections/Forgetting")
    for s in report["per_session"]:
        fg = s["forgetting"]
        fnote = ""
        if fg["expired_outcomes"]:
            fnote += f" expired={len(fg['expired_outcomes'])}"
        if fg["stale_preferences"]:
            fnote += f" stale_prefs={len(fg['stale_preferences'])}"
        bar = "█" * int(round(s["total"]))
        print(f"{s['session']:<9}{s['total']:<8}{s['avg_context_tokens']:<11}"
              f"+{s['corrections_applied']} corr{fnote:<14} {bar}")
    print(f"\nGain (session {report['sessions']} - session 1): +{report['gain']} points")
    print(f"saved -> {out_json}" + (f" and {png}" if png else ""))


if __name__ == "__main__":
    main()
