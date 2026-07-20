"""Memory that LEARNS the gates — real Qwen, no mock, no hardcoded rules.

The gated planner proved the trap/risk gates work, but it *hand-codes* them. This
shows the honest version: the model discovers each gate itself, from what backfired.

Loop (all real LLM):
  1. decide  — Qwen reads the account AND the lessons it has written so far, then
     recommends the action(s). Nothing about the traps is coded in; on session 1 it
     has no lessons and over-acts, exactly like the raw planner.
  2. outcome — the account reveals what actually worked (the ground-truth call).
  3. reflect — when it was wrong, Qwen writes ITS OWN one-line lesson about the
     signals it should have weighted (e.g. "conversions collapsing while clicks hold
     is a tracking bug — fix tracking, don't move budget"). Stored in the Track 1
     memory (SQLite + half-life forgetting).
  4. next session the lesson is in context, so the same trap — even on a different
     campaign — is now gated. The medium/trap tier climbs as the gates are learned.

    python -m track1.memory_llm --sessions 4        # real Qwen Cloud
"""
import argparse
import json

from cmo.agents import PlannerLLMAgent, describe_account
from cmo.benchmark import generate
from cmo.datagen import generate_base
from cmo.harness import score
from cmo.tools import ScenarioEnv
from tracks.track1.memory_store import MemoryStore
from tracks.track1.retriever import Retriever, get_embedder

DECIDE_SYS = (
    "You are an AI copilot for marketing budget decisions. Each week you read the account and recommend "
    "what to do with the budget — which can be SEVERAL actions (a plan), a single fix, or nothing at all. "
    "Actions: refresh_creative, fix_targeting, launch_campaign, increase_budget, decrease_budget, "
    "shift_budget, fix_tracking, no_action. Sometimes the right call is to HOLD — not every dip is a "
    "problem you should act on.\n"
    "LESSONS you have learned from past weeks at THIS account (apply them — they were paid for in "
    "mistakes):\n{lessons}\n"
    "Reply with ONLY a JSON object: {\"items\": [{\"group\": \"G1..G5 or null for a new campaign\", "
    "\"action\": \"<action>\"}], \"rationale\": \"<one sentence>\"}. An empty items list means hold.")

REFLECT_SYS = (
    "You are a marketing copilot. You took an action last week and now you can see the OUTCOME — what actually happened "
    "to the account after your decision. Learn from it. Write ONE general, reusable rule of the form 'When "
    "<a signal you can observe next time>, <what to do>' — about the pattern, not this one campaign, so you "
    "handle it better on ANY campaign in future. Base it strictly on the outcome you observed; you are NOT "
    "told the 'right answer', you must infer it from what happened. Reply with ONLY the sentence.")


_READABLE = {"no_action": "hold — do nothing", "fix_tracking": "fix conversion tracking",
             "increase_budget": "increase the budget", "decrease_budget": "cut the budget",
             "refresh_creative": "refresh the creative", "fix_targeting": "fix the targeting",
             "launch_campaign": "launch a new campaign", "shift_budget": "shift budget between campaigns",
             "multi": "a multi-step plan"}


def _did(decision):
    """Plain-language description of what the model actually did."""
    items = decision.get("items")
    if items:
        return "; ".join(f"{_READABLE.get(it['action'], it['action'])} on "
                         f"{it.get('group') or 'a new campaign'}" for it in items)
    return _READABLE.get(decision.get("action"), decision.get("action"))


# --- Outcome monitor: the environment reveals the KPI consequence of the action.
#     Grounded in the true dynamics (the env generated the data), but it NEVER
#     states the correct action — it reports what happened, with the evidence a
#     real post-mortem would surface, and the model must infer the lesson. ---
_HOLD_WHY = {
    "seasonality": "the whole account was down together that week — an external, seasonal move — so nothing you shifted changed the trend",
    "noise": "the movement was inside normal week-to-week variance; there was no real problem there to fix",
    "brand_demand_dip": "brand-name demand simply softened for external reasons, and that campaign is the protected floor — it recovered on its own",
    "learning_phase": "that campaign had been rebuilt days earlier and was still in its learning phase; touching it only reset that progress",
}


def outcome(decision, expected):
    """Return (polarity in {+1,0,-1}, narrative). Positive = it worked."""
    if _worked(decision, expected):
        return 1, "✓ It worked — over the following 14 days ROAS recovered toward its prior level."
    root, action = expected.get("root_cause"), decision.get("action")
    if root in _HOLD_WHY:
        if action == "no_action":
            return 1, "✓ Holding was right — ROAS drifted back on its own with no intervention."
        return -1, (f"✗ Your change did not help — {_HOLD_WHY[root]}. The intervention spent budget "
                    f"and effort for no gain.")
    if root == "tracking_outage":
        return -1, ("✗ ROAS stayed down after your change. A later audit found conversions WERE happening "
                    "but were not being recorded, and clicks had been completely normal the whole time — "
                    "the performance was never the problem.")
    if root == "budget_cap":
        return -1, ("✗ No improvement — this campaign was efficient and improving, but it was hitting its "
                    "daily budget ceiling and leaving winning demand unspent.")
    if root == "creative_fatigue":
        return -1, ("✗ No improvement — once people clicked they still converted normally; the trouble was "
                    "that far fewer people were clicking the ad than before.")
    if root == "audience_saturation":
        return -1, ("✗ No improvement — people kept clicking at the usual rate, but far fewer of those "
                    "clicks converted than before.")
    if root == "emerging_segment":
        return -1, ("✗ You left a surging audience unserved — a small segment was converting far above the "
                    "account average on a tiny slice of spend, and it stayed uncaptured.")
    if expected.get("plan"):
        sp, _ = score(decision, expected)
        return (0 if sp > 0 else -1,
                "△ Only partly worked — some campaigns recovered but others you left untouched stayed a "
                "drag on ROAS, and a growing audience went uncaptured.")
    return -1, "✗ ROAS did not recover after your change."


def _situation(env):
    """The real account state an analyst would read — metrics + any opportunity."""
    metrics = env.call("get_campaign_metrics", {})
    text = describe_account(metrics)
    opps = env.call("find_opportunities", {}).get("opportunities")
    if opps:
        o = opps[0]
        text += (f"\n- Audience signal: the '{o['segment']}' audience is converting at ROAS "
                 f"{o['recent_roas']} (+{o['roas_change_pct']}%) on only {o['spend_share_pct']}% of spend.")
    return text


def _worked(decision, expected):
    """Did the KPI recover? Judged on the ACTION taken (what drives the outcome),
    not on whether the model labelled the root cause correctly."""
    if expected.get("plan"):
        s, _ = score(decision, expected)          # plan -> F1 of the actions taken
        return s >= 0.8
    if decision.get("action") != expected["action"]:
        return False
    if expected["action"] in ("shift_budget", "increase_budget", "decrease_budget"):
        return decision.get("target_campaign") in expected["acceptable_targets"]
    return True                                    # non-budget action matched


class MemoryLLM:
    """One Qwen call to decide (with lessons in context); one to reflect on a miss."""

    def __init__(self, model=None):
        from cmo.llm import default_live_llm
        self.llm = default_live_llm(model=model)
        self.model = model

    def decide(self, situation, lessons):
        block = "\n".join(f"  - {t}" for t in lessons) if lessons else "  (none yet)"
        self.llm.reset()
        msg = self.llm.complete([
            {"role": "system", "content": DECIDE_SYS.replace("{lessons}", block)},
            {"role": "user", "content": situation}])
        content = (msg.content or "").strip()
        if not content:               # empty = API/quota failure — never silently score garbage
            raise RuntimeError("empty LLM response (Qwen quota or API error?)")
        return PlannerLLMAgent._to_decision(content)

    def reflect(self, situation, did, narrative):
        self.llm.reset()
        user = (f"The account last week:\n{situation}\n\n"
                f"You decided: {did}\n"
                f"Outcome observed: {narrative}\n\n"
                f"Write the one-sentence rule you'll apply next time you see this pattern.")
        msg = self.llm.complete([{"role": "system", "content": REFLECT_SYS},
                                 {"role": "user", "content": user}])
        return (msg.content or "").strip().strip('"')


def curated_questions():
    """A small set spanning the traps (with two tracking cases, to show the learned
    gate GENERALISE to a new campaign) plus a simple and a complex control."""
    scen = generate()
    by_root = {}
    for s in scen:
        r = s["expected"].get("root_cause")
        by_root.setdefault(r, []).append(s)
    pick = []
    pick += by_root["tracking_outage"][:2]          # two -> tests generalisation
    for root in ("seasonality", "brand_demand_dip", "learning_phase", "budget_cap"):
        pick += by_root[root][:1]
    pick += by_root["creative_fatigue"][:1]         # simple control (should stay right)
    pick += [s for s in scen if s["difficulty"] == "complex"][:1]
    return pick


def run(sessions=4, model=None, db_path=None, questions=None):
    import time
    base = generate_base()
    questions = questions or curated_questions()
    store = MemoryStore(db_path or "runs/memory_llm.db")
    # selective retrieval: only the lessons relevant to THIS week's account are
    # injected (relevance x recency x weight, token-capped) — so trap lessons stop
    # interfering with clean-cut cases. Embeddings via Model Studio; lexical fallback.
    retriever = Retriever(store, embedder=get_embedder(mock=False), token_cap=500)
    agent = MemoryLLM(model=model)
    evolution, stopped = [], None

    def _save():
        gate_book = [{"topic": m.topic, "lesson": m.text}
                     for m in store.list_active() if m.kind == "preference"]
        with open("runs/memory_llm_evolution.json", "w") as f:
            json.dump({"n_questions": len(questions), "sessions_done": len(evolution),
                       "stopped": stopped, "evolution": evolution, "gate_book": gate_book}, f, indent=2)

    for sess in range(1, sessions + 1):
        held = len([m for m in store.list_active() if m.kind == "preference"])
        rows, new_lessons, recalled_counts, confirmed = [], [], [], 0
        for i, q in enumerate(questions):
            env = ScenarioEnv(base, q)
            situation = _situation(env)
            recalled = retriever.retrieve(situation, sess).memories[:2]   # top-2 relevant gates
            lessons = [m.text for m in recalled]
            recalled_counts.append(len(lessons))
            try:
                decision = agent.decide(situation, lessons)
            except Exception as e:                   # API/quota failure -> stop; never score garbage
                stopped = f"session {sess}, {q['id']} ({i + 1}/{len(questions)}): {type(e).__name__}: {e}"
                break
            s, _ = score(decision, q["expected"])
            rows.append({"id": q["id"], "difficulty": q["difficulty"], "score": s,
                         "recalled": len(lessons)})
            pol, narrative = outcome(decision, q["expected"])   # the account reveals what happened
            topic = q["expected"].get("root_cause")
            if pol > 0:                              # POSITIVE outcome -> confirm the gates that worked (keep them)
                for m in recalled:
                    store.confirm_preference(m.id, sess)
                    confirmed += 1
            else:                                    # NEGATIVE/partial -> revise this topic's gate from the outcome
                try:
                    lesson = agent.reflect(situation, _did(decision), narrative)
                except Exception:
                    lesson = ""
                if lesson:
                    for m in store.list_active():    # one gate per trap type — the failed one is demoted
                        if m.kind == "preference" and m.topic == topic:
                            store.set_status(m.id, "demoted")
                    store.add("preference", lesson, sess, topic=topic)
                    new_lessons.append(lesson)
        if not rows:                                 # failed before any question completed
            _save()
            break
        store.apply_forgetting(sess)
        def tier(t):
            r = [x for x in rows if x["difficulty"] == t]
            return round(100 * sum(x["score"] for x in r) / len(r), 1) if r else None

        total = round(100 * sum(r["score"] for r in rows) / len(rows), 1)
        sp, mp, cp = tier("simple"), tier("medium"), tier("complex")
        avg_recalled = round(sum(recalled_counts) / len(recalled_counts), 1)
        gate_book = [{"topic": m.topic, "lesson": m.text}
                     for m in store.list_active() if m.kind == "preference"]
        evolution.append({"session": sess, "overall_pct": total, "simple_pct": sp,
                          "medium_pct": mp, "complex_pct": cp, "trap_pct": mp,
                          "avg_recalled_per_decision": avg_recalled,
                          "gates_confirmed": confirmed, "gates_revised": len(new_lessons),
                          "total_gates": len(gate_book), "gate_book": gate_book})
        # --- CHECKPOINT: performance this session + the memory (gate-book) right now ---
        print(f"\n{'='*72}\n  CHECKPOINT — after Session {sess}\n{'='*72}")
        print(f"  Performance:  overall {total}%   |   simple {sp}%   medium/traps {mp}%   complex {cp}%")
        print(f"  Feedback:     {confirmed} gates CONFIRMED (worked ✓)   {len(new_lessons)} REVISED (backfired ✗)")
        print(f"  Memory:       {len(gate_book)} gates held   (~{avg_recalled} recalled/decision)")
        if gate_book:
            print(f"  The gate-book CMO Copilot has learned so far:")
            for g in gate_book:
                print(f"     • [{g['topic']}] {g['lesson']}")
        _save()                                      # persist after every session
        if stopped:
            print(f"\n⚠️  STOPPED at {stopped}\n    (likely Qwen quota). Kept {len(evolution)} complete session(s).")
            break

    print(f"\n{'='*70}\nMEMORY EVOLUTION\n{'='*70}")
    print(f"{'Session':<9}{'Overall':<9}{'Simple':<8}{'Traps':<8}{'Complex':<9}{'Gates held'}")
    for e in evolution:
        print(f"{e['session']:<9}{e['overall_pct']:<9}{e['simple_pct']:<8}"
              f"{e['medium_pct']:<8}{e['complex_pct']:<9}{e['total_gates']}")
    if stopped:
        print(f"\n⚠️  run stopped early ({stopped}) — {len(evolution)} session(s) completed.")
    print("\nFinal learned gate-book (the lessons CMO Copilot wrote for itself):")
    for m in store.list_active():
        if m.kind == "preference":
            print(f"  [{m.topic}] {m.text}")
    _save()
    store.close()
    return evolution


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sessions", type=int, default=4)
    ap.add_argument("--model", default=None)
    ap.add_argument("--db", default="runs/memory_llm.db")
    ap.add_argument("--all", action="store_true", help="all 100 questions (default: curated subset)")
    args = ap.parse_args()
    import os
    if os.path.exists(args.db):
        os.remove(args.db)     # fresh learning run
    run(sessions=args.sessions, model=args.model, db_path=args.db,
        questions=(generate() if args.all else None))
