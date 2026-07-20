"""Eval harness: run an agent over the 10 scenarios and score it.

Usage:
  python harness.py --agent mock          # offline, no API key needed
  python harness.py --agent qwen          # needs DASHSCOPE_API_KEY

Scoring per scenario (0..1):
  0.4  root cause correct
  0.4  action correct
  0.2  sourcing correct (target acceptable, source allowed) — automatic when
       the expected action has no source/target.
"""
import argparse
import json
import time
from cmo.config import RUNS_DIR
from cmo.datagen import generate_base
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv

# Actions that move money — these are the ones with a source/target to get right,
# and the only ones that can violate the brand floor.
BUDGET_ACTIONS = ("shift_budget", "increase_budget", "decrease_budget")
# Actions that fix something without touching budget. On a no-move scenario these
# earn full sourcing credit: the agent correctly left the money alone.
NON_BUDGET_ACTIONS = ("no_action", "fix_tracking", "fix_landing_page", "refresh_creative",
                      "fix_targeting", "launch_campaign", "pause_campaign")


def _plan_pairs(items):
    """A plan as a set of (group, action) tuples — the unit plan scoring compares."""
    return {(it.get("group"), it.get("action")) for it in (items or [])}


def score_plan(decision, expected):
    """Set-based scoring for a MULTI-ITEM plan: F1 over (group, action) items.

    Recommending the right fixes (recall) AND not inventing spurious ones
    (precision) both count, so the score rewards a complete-but-tight plan. A
    single-action agent is graded as a length-1 plan — its one move must be one
    of the expected items to earn anything, which is why the naive baseline
    scores ~0 here: it can only ever name one of the several things to do.
    """
    exp = _plan_pairs(expected["plan"])
    items = decision.get("items")
    if items:
        got = _plan_pairs(items)
    else:  # a single-action decision, treated as a one-item plan
        got = {(decision.get("target_campaign") or decision.get("source_campaign"),
                decision.get("action"))}
    tp = len(got & exp)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(exp) if exp else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    notes = []
    missed, spurious = exp - got, got - exp
    if missed:
        notes.append("missed: " + ", ".join(f"{g or 'new'}:{a}" for g, a in sorted(missed, key=str)))
    if spurious:
        notes.append("spurious: " + ", ".join(f"{g or 'new'}:{a}" for g, a in sorted(spurious, key=str)))
    return round(f1, 2), notes


def score(decision, expected):
    if expected.get("plan"):          # multi-item scenarios route to plan scoring
        return score_plan(decision, expected)
    s, notes = 0.0, []
    if decision.get("root_cause") == expected["root_cause"]:
        s += 0.4
    else:
        notes.append(f"root_cause {decision.get('root_cause')} != {expected['root_cause']}")
    if decision.get("action") == expected["action"]:
        s += 0.4
    else:
        notes.append(f"action {decision.get('action')} != {expected['action']}")

    if expected["action"] in BUDGET_ACTIONS:
        tgt_ok = decision.get("target_campaign") in expected["acceptable_targets"]
        src = decision.get("source_campaign")
        src_ok = (src not in expected["forbidden_sources"]) and (
            not expected["acceptable_sources"] or src in expected["acceptable_sources"])
        if decision.get("action") in BUDGET_ACTIONS and tgt_ok and src_ok:
            s += 0.2
        else:
            notes.append("sourcing wrong (target/source)")
    else:
        # no-move scenarios: full sourcing credit iff the agent also didn't move money
        if decision.get("action") in NON_BUDGET_ACTIONS:
            s += 0.2
        else:
            src = decision.get("source_campaign")
            if src in expected["forbidden_sources"]:
                notes.append(f"moved budget out of protected campaign {src}")
    return round(s, 2), notes


def run(agent):
    base = generate_base()
    results = []
    for sc in SCENARIOS:
        env = ScenarioEnv(base, sc)
        t0 = time.time()
        try:
            decision = agent.decide(env)
        except Exception as e:  # an agent crash scores 0, never kills the run
            decision = {"root_cause": "ERROR", "action": "ERROR", "rationale": str(e)}
        sc_score, notes = score(decision, sc["expected"])
        results.append({
            "scenario": sc["id"], "name": sc["name"], "score": sc_score,
            "decision": decision, "expected": sc["expected"], "notes": notes,
            "tool_calls": len(env.tool_log), "latency_s": round(time.time() - t0, 2),
        })
    return results


def report(agent_name, results):
    total = sum(r["score"] for r in results)
    print(f"\n{'='*74}\nAgent: {agent_name}   Total: {total:.1f} / {len(results)}\n{'='*74}")
    print(f"{'ID':<5}{'Scenario':<38}{'Score':<7}{'Calls':<7}Notes")
    for r in results:
        print(f"{r['scenario']:<5}{r['name'][:36]:<38}{r['score']:<7}{r['tool_calls']:<7}"
              f"{'; '.join(r['notes'])[:60] or 'OK'}")
    RUNS_DIR.mkdir(exist_ok=True)
    out = RUNS_DIR / f"results_{agent_name}_{int(time.time())}.json"
    with open(out, "w") as f:
        json.dump({"agent": agent_name, "total": total, "results": results}, f, indent=2)
    print(f"\nsaved -> {out}")
    return total


def build_agent(name, mock=False):
    if name == "mock":
        from cmo.agents import MockHeuristicAgent
        return MockHeuristicAgent()
    if name == "qwen":
        from cmo.agents import QwenBaselineAgent
        return QwenBaselineAgent()
    if name == "society":
        from tracks.track3.society import SocietyAgent
        return SocietyAgent(mock=mock)
    raise ValueError(f"unknown agent {name}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", choices=["mock", "qwen", "society"], default="mock")
    ap.add_argument("--mock", action="store_true",
                    help="force offline/mock brains (society); 'mock' agent is always offline")
    args = ap.parse_args()
    agent = build_agent(args.agent, mock=args.mock)
    report(agent.name, run(agent))
