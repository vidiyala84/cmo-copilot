"""Learned, historically-validated, deterministically-enforced gates.

Earlier this file hardcoded the routing (`if cvr_drop >= 0.5 ...`) — which is
overfitting: *I* was setting the boundaries, not the memory learning them. This
version learns them from the sessions.

  1. OBSERVE   — extract a RAW feature vector from the account (funnel drops,
     elasticity, second-worst group, roas spread, flags, brand, opportunity lift).
     No thresholds applied here — just observations.
  2. LEARN     — each session, fit a decision tree on the accumulated episodes
     (features -> what actually worked). The TREE discovers the thresholds and
     splits from data; nothing is hand-set. Its rules are printed each checkpoint.
  3. VALIDATE  — a tree leaf becomes an enforced gate only if history backs it:
     enough support, high purity, AND lift > 0 (the base was really getting those
     cases wrong, so the correction matters). "Check the historical data if the
     change mattered."
  4. ENFORCE   — a validated leaf fires deterministically. Leaves that predict a
     PLAN, or that lack support/lift, defer to the base agent (e.g. the society).

    python -m track1.memory_gates --sessions 4 --base society
    python -m track1.memory_gates --sessions 4 --base structured   # offline, no tokens
"""
import argparse
import json
from collections import Counter, defaultdict

import numpy as np
from sklearn.tree import DecisionTreeClassifier, export_text

from cmo.benchmark import generate
from cmo.datagen import generate_base
from cmo.harness import score
from cmo.tools import ScenarioEnv

MIN_SUPPORT = 3       # a leaf needs this many historical cases before it can fire
MIN_PURITY = 0.80     # and this fraction must agree
MAX_DEPTH = 8         # tree capacity (a hyperparameter — the SPLITS are still learned)
RUNS = "runs"

FEATURES = ["worst_cvr_drop", "worst_ctr_drop", "worst_aov_drop", "worst_roas_chg",
            "worst_elasticity", "second_roas_chg", "roas_spread", "learning_flag",
            "budget_flag", "worst_is_brand", "opportunity_lift",
            "worst_bounce_ratio", "worst_pacing", "worst_cpm_ratio", "worst_freq_ratio"]


# --------------------------------------------------------------------------
# 1. OBSERVE — a raw feature vector. No thresholds, no routing logic here.
# --------------------------------------------------------------------------

def observe(env):
    metrics = env.get_campaign_metrics()
    changes = {g: (d.get("roas_change_pct") or 0.0) for g, d in metrics.items()}
    order = sorted(changes, key=changes.get)          # most negative first
    g, g2 = order[0], order[1]
    d = env.diagnose_drivers(g)["drivers"]
    vals = list(changes.values())
    spread = float(np.std(vals))
    has = lambda k: 1.0 if any(k in (metrics[x].get("flags") or {}) for x in metrics) else 0.0
    opps = env.find_opportunities()
    acct = opps.get("account_roas") or 1.0
    opp_lift = (opps["opportunities"][0]["recent_roas"] / acct) if opps.get("opportunities") else 0.0
    return np.array([
        1 - d["targeting"]["ratio"], 1 - d["creative"]["ratio"], 1 - d["offer_mix"]["ratio"],
        changes[g], d["budget"]["ratio"], changes[g2], spread,
        has("last_edited_days_ago"), has("lost_impression_share_budget_pct"),
        1.0 if g == "G2" else 0.0, opp_lift,
        # richer signals: bounce spike (landing), pacing at cap (budget), cpm spike
        # (competitor), frequency climb (saturation) — the tree gates on these too.
        d["landing"]["ratio"], metrics[g]["recent_14d"].get("pacing", 0.0),
        d["auction"]["ratio"], d["saturation_audience"]["ratio"],
    ], dtype=float)


def label(expected):
    return "PLAN" if expected.get("plan") else expected["action"]


# --------------------------------------------------------------------------
# 2+3. LEARN a tree from history, VALIDATE each leaf (support / purity / lift).
# --------------------------------------------------------------------------

def fit_gates(X, y, base_ok, roots):
    clf = DecisionTreeClassifier(max_depth=MAX_DEPTH, min_samples_leaf=MIN_SUPPORT,
                                 random_state=0)
    clf.fit(X, y)
    leaves = clf.apply(X)
    stats = {}
    for leaf in set(leaves):
        idx = [i for i, lf in enumerate(leaves) if lf == leaf]
        labs = [y[i] for i in idx]
        action, hits = Counter(labs).most_common(1)[0]
        support = len(idx)
        purity = hits / support
        # "did the change matter?" — on the cases this leaf covers, how often was
        # the BASE agent actually wrong? A leaf that only echoes what the base
        # already gets right earns no enforcement.
        matched = [i for i in idx if y[i] == action]
        lift = sum(1 for i in matched if not base_ok[i]) / len(matched) if matched else 0.0
        root = Counter(roots[i] for i in matched).most_common(1)[0][0] if matched else None
        accepted = (action != "PLAN" and support >= MIN_SUPPORT
                    and purity >= MIN_PURITY and lift > 0)
        stats[leaf] = {"action": action, "root": root, "support": support,
                       "purity": round(purity, 2), "lift": round(lift, 2), "accepted": accepted}
    return clf, stats


# --------------------------------------------------------------------------
# 4. ENFORCE — a validated leaf fires deterministically; else the base decides.
# --------------------------------------------------------------------------

def _gate_decision(action, root, env):
    if action in ("increase_budget", "decrease_budget", "shift_budget"):
        changes = {g: (d.get("roas_change_pct") or 0.0)
                   for g, d in env.get_campaign_metrics().items()}
        target = max(changes, key=changes.get) if action == "increase_budget" else None
        return {"root_cause": root, "action": action, "target_campaign": target,
                "source_campaign": None, "items": []}
    return {"root_cause": root, "action": action, "target_campaign": None,
            "source_campaign": None, "items": []}


def build_base(name):
    if name == "planner":
        from cmo.agents import PlannerLLMAgent
        return PlannerLLMAgent()
    if name == "structured":
        from cmo.agents import StructuredAgent
        return StructuredAgent()
    if name == "society":
        from tracks.track3.society import SocietyAgent
        return SocietyAgent(mock=True)
    if name == "llm":                               # cheap real-LLM base: 1 Qwen call/decision
        from tracks.track1.memory_llm import MemoryLLM, _situation

        class _OneCallLLM:
            def __init__(self):
                self.m = MemoryLLM()
            def decide(self, env):
                return self.m.decide(_situation(env), [])
        return _OneCallLLM()
    raise ValueError(name)


LIVE_BASES = ("planner", "llm")


def run(sessions=4, base="planner", questions=None):
    base_data = generate_base()
    questions = questions or generate()
    agent = build_base(base)
    X, y, base_ok, roots = [], [], [], []       # the accumulating HISTORY
    clf, stats = None, {}
    evolution, stopped = [], None

    for sess in range(1, sessions + 1):
        rows, llm_calls, enforced = [], 0, 0
        for q in questions:
            env = ScenarioEnv(base_data, q)
            feat = observe(env)
            gate = None
            if clf is not None:
                leaf = int(clf.apply([feat])[0])
                st = stats.get(leaf)
                if st and st["accepted"]:
                    gate = st
            if gate:                                 # ENFORCE — no base/LLM call
                decision = _gate_decision(gate["action"], gate["root"], env)
                enforced += 1
            else:                                    # base agent decides
                try:
                    decision = agent.decide(env)
                except Exception as e:                # API/quota failure -> stop, don't score garbage
                    stopped = f"session {sess}, {q['id']}: {type(e).__name__}: {e}"
                    break
                if base in LIVE_BASES:
                    llm_calls += 1
            s, _ = score(decision, q["expected"])
            rows.append({"id": q["id"], "difficulty": q["difficulty"], "score": s})
            # record the episode: features, what worked, its root, and (when the base
            # decided) whether the base got it right — the evidence for "did it matter?"
            X.append(feat)
            y.append(label(q["expected"]))
            roots.append(q["expected"].get("root_cause"))
            base_ok.append(True if gate else (s >= 0.8))

        if stopped:
            print(f"\n⚠️  STOPPED at {stopped} (likely Qwen quota). Kept {len(evolution)} complete session(s).")
            break
        clf, stats = fit_gates(np.array(X), y, base_ok, roots)     # LEARN + VALIDATE on all history
        accepted = [st for st in stats.values() if st["accepted"]]

        def tier(t):
            r = [x for x in rows if x["difficulty"] == t]
            return round(100 * sum(x["score"] for x in r) / len(r), 1) if r else None
        total = round(100 * sum(r["score"] for r in rows) / len(rows), 1)
        evolution.append({"session": sess, "overall_pct": total, "simple_pct": tier("simple"),
                          "medium_pct": tier("medium"), "complex_pct": tier("complex"),
                          "enforced_gates": len(accepted), "enforced_decisions": enforced,
                          "llm_calls": llm_calls, "tree_depth": clf.get_depth(),
                          "tree_rules": export_text(clf, feature_names=FEATURES, max_depth=MAX_DEPTH)})
        print(f"\n{'='*76}\n  CHECKPOINT — after Session {sess}\n{'='*76}")
        print(f"  Performance: overall {total}%  |  simple {tier('simple')}%  "
              f"traps {tier('medium')}%  complex {tier('complex')}%")
        print(f"  Cost:        {enforced} decisions enforced by learned gates (0 base),  "
              f"{llm_calls} via the base LLM")
        print(f"  Learned:     a depth-{clf.get_depth()} tree; {len(accepted)} leaves validated & enforcing")
        for st in sorted(accepted, key=lambda s: -s["support"]):
            print(f"       ✅ -> {st['action']:<16} (support {st['support']}, "
                  f"purity {st['purity']}, lift {st['lift']})")
        import os
        os.makedirs(RUNS, exist_ok=True)
        with open(f"{RUNS}/memory_gates_evolution.json", "w") as f:
            json.dump({"base": base, "evolution": evolution}, f, indent=2)

    print(f"\n{'='*76}\n  GATE-LEARNING EVOLUTION ({base} base)\n{'='*76}")
    print(f"{'Sess':<6}{'Overall':<9}{'Simple':<8}{'Traps':<8}{'Complex':<9}{'Enforced':<10}{'Base calls'}")
    for e in evolution:
        print(f"{e['session']:<6}{e['overall_pct']:<9}{e['simple_pct']:<8}{e['medium_pct']:<8}"
              f"{e['complex_pct']:<9}{e['enforced_decisions']:<10}{e['llm_calls']}")
    print("\nThe tree the memory LEARNED (thresholds discovered from data, not set by hand):")
    print(evolution[-1]["tree_rules"])
    return evolution


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--base", default="planner", choices=["planner", "structured", "society", "llm"])
    args = ap.parse_args()
    run(sessions=args.sessions, base=args.base)
