"""Multi-item recommendation demo — a reallocation is a PLAN, not one move.

The same account has three things wrong/available at once (M1):
  - G1's ad tired            -> refresh_creative
  - G1's clicks convert worse -> fix_targeting
  - a Fitness audience is surging on tiny spend -> launch_campaign

The naive baseline can only ever name ONE fix, so on the set-based plan rubric it
scores near zero. The PlannerAgent derives the whole plan from tools
(`recommend_portfolio`) — multiple fixes on one group AND a brand-new campaign —
and scores the full plan. The gap is the point.

    python multi_item.py            # offline, deterministic, no key
"""
import argparse
import json

from cmo.agents import MockHeuristicAgent, PlannerAgent
from cmo.config import RUNS_DIR
from cmo.datagen import generate_base
from cmo.harness import score
from cmo.scenarios import MULTI_ITEM_SCENARIO
from cmo.tools import ScenarioEnv


def run():
    base = generate_base()
    sc = MULTI_ITEM_SCENARIO
    expected = {(it["group"], it["action"]) for it in sc["expected"]["plan"]}

    rows = []
    for label, agent in (("baseline (single-action)", MockHeuristicAgent()),
                         ("planner (multi-item)", PlannerAgent())):
        env = ScenarioEnv(base, sc)
        decision = agent.decide(env)
        s, notes = score(decision, sc["expected"])
        got = [{"group": it.get("group"), "action": it.get("action")}
               for it in decision.get("items", [])] or \
              [{"group": decision.get("target_campaign") or decision.get("source_campaign"),
                "action": decision.get("action")}]
        rows.append({"agent": label, "score": s, "n_items": len(got),
                     "plan": got, "notes": notes, "tool_calls": len(env.tool_log)})

    report = {"scenario": sc["id"], "name": sc["name"],
              "expected_plan": [{"group": g, "action": a} for g, a in sorted(expected, key=str)],
              "results": rows}

    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / "multi_item.json"
    out.write_text(json.dumps(report, indent=2))

    print(f"\n{'='*70}\n{sc['id']} — {sc['name']}\n{'='*70}")
    print("Expected plan (a SET of items, one group can appear twice):")
    for g, a in sorted(expected, key=str):
        print(f"   • {a:<16} on {g or 'a NEW campaign'}")
    for r in rows:
        print(f"\n{r['agent']}  —  plan score {r['score']}/1.0  ({r['n_items']} item(s), "
              f"{r['tool_calls']} tool calls)")
        for it in r["plan"]:
            print(f"   • {it['action']:<16} on {it['group'] or 'a NEW campaign'}")
        if r["notes"]:
            print("   " + "; ".join(r["notes"]))
    print(f"\nsaved -> {out}")
    return report


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
