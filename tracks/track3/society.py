"""H2-2 — the four-agent society (Track 3).

Analyst (diagnosis) + Forecaster (eager optimizer) + Risk (guardrail veto) +
Coordinator (synthesis). They genuinely disagree — the Forecaster always wants
to move budget; the Analyst's diagnosis and the Risk Officer's veto rein it in —
and the Coordinator resolves the conflict with the coded policy in protocol.py.

The society beats the single-agent baseline **by construction of its structure**:
a dedicated diagnosis specialist reads flags/brand context the naive baseline
ignores, and the Risk veto makes the trap scenarios (S07 brand floor, S08
learning phase) impossible to get wrong.

`SocietyAgent.decide(env)` plugs straight into `harness.py --agent society`.
Each decision writes a full transcript to runs/transcripts/<scenario>.json.
"""
import json
import time
from pathlib import Path

from cmo.config import MODELS, RUNS_DIR
from cmo.portfolio import GROUP_IDS, GROUP_META
from cmo.tools import OPENAI_TOOL_SPECS
from tracks.track3.protocol import Message, detect_conflict, run_debate

BRAND = "G2"
NO_ACTION_ROOTS = {"seasonality", "noise", "brand_demand_dip", "learning_phase", "funnel_leak"}
KIND = {gid: meta["kind"] for gid, meta in GROUP_META.items()}
PROMPTS_DIR = Path(__file__).parent / "prompts"


# ================================================================= mock brains

def analyst_diagnose(metrics: dict):
    """Root-cause diagnosis from observable signals. The specialist's edge over
    the naive baseline: it reads flags and campaign kind."""
    changes = {cid: (d.get("roas_change_pct") or 0.0) for cid, d in metrics.items()}
    problem = min(changes, key=changes.get)
    best = max(changes, key=changes.get)
    vals = list(changes.values())
    mean = sum(vals) / len(vals)
    spread = max(vals) - min(vals)

    # 1) flags win
    for cid, d in metrics.items():
        fl = d.get("flags") or {}
        if "last_edited_days_ago" in fl:
            return "learning_phase", cid
        if "lost_impression_share_budget_pct" in fl:
            return "budget_cap", cid

    # 2) conversions collapse while clicks hold — but is it the pixel or the page?
    #    A tracking outage leaves bounce flat; a landing-page break spikes it.
    for cid, d in metrics.items():
        r, p = d["recent_14d"], d["prior_76d"]
        conv = (r["conversions"] / 14) / max(p["conversions"] / 76, 1e-9)
        click = (r["clicks"] / 14) / max(p["clicks"] / 76, 1e-9)
        br = (r.get("bounce_rate") or 0.0) / max(p.get("bounce_rate") or 1e-9, 1e-9)
        if conv < 0.6 and click > 0.85 and br > 1.4:
            return "landing_page_break", cid
        if conv < 0.4 and click > 0.85 and br < 1.25:
            return "tracking_outage", cid

    # 2b) funnel leak: ROAS fell but the ad funnel is healthy — revenue per
    #     conversion collapsed downstream. Hold the ads; the leak is past the click.
    for cid, d in metrics.items():
        if (d.get("roas_change_pct") or 0.0) >= -12:
            continue
        r, p = d["recent_14d"], d["prior_76d"]
        ctr_r = (r["ctr"] or 0.0) / max(p["ctr"] or 1e-9, 1e-9)
        cvr_r = (r["cvr"] or 0.0) / max(p["cvr"] or 1e-9, 1e-9)
        aov_r = ((r["revenue"] / max(r["conversions"], 1e-9)) /
                 max(p["revenue"] / max(p["conversions"], 1e-9), 1e-9))
        if aov_r < 0.72 and ctr_r > 0.9 and cvr_r > 0.9:
            return "funnel_leak", cid

    # 2c) over-investment: we ramped spend but ROAS fell and frequency climbed. Unlike
    #     audience_saturation (spend flat), the tell is that SPEND ROSE -> pull budget back.
    for cid, d in metrics.items():
        if (d.get("roas_change_pct") or 0.0) >= -10:
            continue
        r, p = d["recent_14d"], d["prior_76d"]
        spend_r = (r["spend"] / 14) / max(p["spend"] / 76, 1e-9)
        freq_r = (r.get("frequency") or 0.0) / max(p.get("frequency") or 1e-9, 1e-9)
        cvr_r = (r["cvr"] or 0.0) / max(p["cvr"] or 1e-9, 1e-9)
        if spend_r > 1.2 and freq_r > 1.15 and cvr_r < 0.92:
            return "over_saturation", cid

    # 3) macro shapes
    if mean < -15 and spread < 16:
        return "seasonality", problem
    if all(abs(v) < 12 for v in vals):
        return "noise", problem
    if changes[best] > 15 and abs(changes[problem]) < 15:
        return "winner_opportunity", best
    if problem == BRAND:
        return "brand_demand_dip", problem

    # 4) disambiguate decline by campaign kind
    kind = KIND.get(problem)
    if kind == "retargeting":
        return "audience_saturation", problem
    if kind == "nonbrand":
        return "competitor_pressure", problem
    return "creative_fatigue", problem


# The fix each diagnosis implies. A ctr collapse is a creative problem, a cvr
# collapse a targeting one — moving budget fixes neither. Only genuine
# supply/demand shifts (competitor, winner) are budget moves.
_ACTION_BY_ROOT = {
    "creative_fatigue": "refresh_creative",
    "audience_saturation": "fix_targeting",
    "landing_page_break": "fix_landing_page",
    "over_saturation": "decrease_budget",
    "dead_campaign": "pause_campaign",
    "emerging_segment": "launch_campaign",
    "tracking_outage": "fix_tracking",
    "budget_cap": "increase_budget",
    "competitor_pressure": "shift_budget",
    "winner_opportunity": "shift_budget",
}


def _implied_action(root):
    if root in NO_ACTION_ROOTS:
        return "no_action"
    return _ACTION_BY_ROOT.get(root, "shift_budget")


def forecaster_plan(root, metrics):
    """Best candidate move (source, target, action). Eager: always finds one."""
    recent_roas = {cid: metrics[cid]["recent_14d"]["roas"] for cid in metrics}
    changes = {cid: (d.get("roas_change_pct") or 0.0) for cid, d in metrics.items()}
    problem = min(changes, key=changes.get)

    def best_target(exclude):
        cands = [c for c in metrics if c not in exclude and c != BRAND]
        return max(cands, key=lambda c: recent_roas[c])

    def weakest_source(exclude):
        cands = [c for c in metrics if c not in exclude and c != BRAND]
        return min(cands, key=lambda c: recent_roas[c])

    if root == "budget_cap":
        target = next((cid for cid, d in metrics.items()
                       if (d.get("flags") or {}).get("lost_impression_share_budget_pct")),
                      max(changes, key=changes.get))
        return "increase_budget", weakest_source({target}), target
    if root == "winner_opportunity":
        target = max(changes, key=changes.get)
        return "shift_budget", weakest_source({target}), target
    if root == "over_saturation":
        # pull budget OUT of the over-invested group; it is both source and subject
        return "decrease_budget", problem, problem
    return "shift_budget", problem, best_target({problem})


# ================================================================= specialists

def _risk_message(env, root, action, source, target):
    """The Risk Officer's constraint check on a proposed plan — deterministic in
    both mock and live mode (a guardrail is a rules check, not a guess). Returns
    a veto Message on a breach, else a conservatively-staged approval."""
    if action not in ("shift_budget", "increase_budget") or not source or not target:
        return Message(agent="Risk", claim={"action": action or "no_action"},
                       evidence=[], confidence=0.9, rationale="No reallocation to validate.")
    check = env.call("propose_reallocation", {"source_campaign": source,
                                              "target_campaign": target, "shift_pct": 20})
    ref = f"propose_reallocation:{source}->{target}:20"
    if not check.get("valid"):
        return Message(
            agent="Risk", claim={"action": "no_action"},
            evidence=[ref], confidence=0.95, rationale="Constraint breach — plan rejected.",
            veto="; ".join(check.get("violations", ["constraint breach"])),
            veto_override={"root_cause": root, "action": "no_action",
                           "source_campaign": None, "target_campaign": None, "shift_pct": None})
    return Message(
        agent="Risk",
        claim={"root_cause": root, "action": action, "source_campaign": source,
               "target_campaign": target, "shift_pct": 15},
        evidence=[ref], confidence=0.8,
        rationale="Plan valid; stage conservatively at 15% for week-one pacing.")


def _mock_specialists(env, metrics):
    """Produce the three specialist Messages (mock/offline). Tools are actually
    called so every claim's evidence maps to a real tool result (audit trail)."""
    root, problem = analyst_diagnose(metrics)
    analyst = Message(
        agent="Analyst",
        claim={"root_cause": root, "action": _implied_action(root)},
        evidence=["get_campaign_metrics"], confidence=0.9,
        rationale=f"{problem} is the locus; diagnosis = {root}.")

    action, source, target = forecaster_plan(root, metrics)
    fc = env.call("forecast_roas", {"source_campaign": source,
                                    "target_campaign": target, "shift_pct": 20})
    forecaster = Message(
        agent="Forecaster",
        claim={"root_cause": root, "action": action, "source_campaign": source,
               "target_campaign": target, "shift_pct": 20},
        evidence=[f"forecast_roas:{source}->{target}:20"], confidence=0.7,
        rationale=f"Move 20% {source}->{target}; projected daily delta "
                  f"{fc.get('expected_daily_revenue_delta')}.")

    risk = _risk_message(env, root, action, source, target)
    return analyst, forecaster, risk


# ================================================================= coordinator

def society_ruling(messages):
    """The Coordinator's coded synthesis policy. Returns (final_claim, reason)."""
    by = {m.agent: m for m in messages}
    analyst, forecaster, risk = by.get("Analyst"), by.get("Forecaster"), by.get("Risk")
    root = analyst.claim.get("root_cause", "noise") if analyst else "noise"
    hold = {"root_cause": root, "action": "no_action", "source_campaign": None,
            "target_campaign": None, "shift_pct": None}

    if risk and risk.veto:
        return hold, f"Risk veto ({risk.veto}); Forecaster's shift blocked"

    diag_action = analyst.claim.get("action") if analyst else "no_action"
    if diag_action in ("no_action", "fix_tracking", "fix_landing_page"):
        return {**hold, "action": diag_action}, \
            f"Analyst diagnosis '{root}' → {diag_action}; declined Forecaster's move"

    # Risk validates shift/increase moves; for a decrease (pull-out) keep the
    # Forecaster's plan, which carries the target group.
    prefer_risk = (risk and diag_action in ("shift_budget", "increase_budget")
                   and risk.claim.get("action") == diag_action)
    plan = risk.claim if prefer_risk else forecaster.claim
    return {"root_cause": root, "action": diag_action,
            "source_campaign": plan.get("source_campaign"),
            "target_campaign": plan.get("target_campaign"),
            "shift_pct": plan.get("shift_pct", 15)}, \
        f"Coordinator: {diag_action} {plan.get('source_campaign')}→{plan.get('target_campaign')} " \
        f"at Risk-approved {plan.get('shift_pct', 15)}%"


def _concede(messages, rnd):
    """Rebuttal: Forecaster concedes to the Risk-approved plan / accepts the veto."""
    out = []
    for m in messages:
        if m.agent == "Forecaster":
            risk = next((x for x in messages if x.agent == "Risk"), None)
            if risk and risk.veto:
                out.append(Message("Forecaster", {"action": "no_action"}, m.evidence,
                                   0.5, "Concede: constraint breach, stand down."))
            elif risk:
                out.append(Message("Forecaster", dict(risk.claim), m.evidence, 0.75,
                                   "Concede: accept staged 15% sizing."))
            else:
                out.append(m)
        else:
            out.append(m)
    return out


# ================================================================= agent

class SocietyAgent:
    name = "society"

    def __init__(self, mock=True, transcripts_dir=None):
        self.mock = mock
        self.transcripts_dir = Path(transcripts_dir) if transcripts_dir else (RUNS_DIR / "transcripts")
        self.last_transcript = None

    def _specialists(self, env, metrics):
        if self.mock:
            return _mock_specialists(env, metrics), {}
        analyst, forecaster, risk, usage = live_specialists(env, metrics)
        return (analyst, forecaster, risk), usage

    def decide(self, env):
        t0 = time.time()
        metrics = env.call("get_campaign_metrics", {})
        (analyst, forecaster, risk), usage = self._specialists(env, metrics)
        initial = [analyst, forecaster, risk]

        result = run_debate(initial, rebut_fn=_concede, max_rounds=2, rule=society_ruling)

        # explicit conflict accounting (covers sizing reconciliation too)
        conflicts = []
        if risk.veto:
            conflicts.append(f"Risk vetoed Forecaster's {forecaster.claim.get('action')} "
                             f"({risk.veto})")
        if forecaster.claim.get("action") != result.ruling.get("action"):
            conflicts.append(f"Forecaster wanted {forecaster.claim.get('action')}, "
                             f"Coordinator ruled {result.ruling.get('action')}")
        elif forecaster.claim.get("shift_pct") != result.ruling.get("shift_pct") \
                and result.ruling.get("shift_pct") is not None:
            conflicts.append(f"Sizing reconciled {forecaster.claim.get('shift_pct')}% → "
                             f"{result.ruling.get('shift_pct')}% (Risk pacing)")
        if not conflicts:
            conflicts.append("specialists aligned after review")

        decision = dict(result.ruling)
        decision["rationale"] = (f"[society] {analyst.rationale} {result.reason}. "
                                 f"Conflicts resolved: {len(conflicts)}.")

        # Growth Lead also scans by AUDIENCE for a structurally dead segment to kill —
        # invisible in the group rollup (a loser can be a rounding error in every group).
        # Only on a genuinely QUIET account: when the whole account is down (seasonality)
        # every segment dips below break-even and find_losers would false-positive.
        group_changes = [d.get("roas_change_pct") or 0.0 for d in metrics.values()]
        if (decision.get("root_cause") == "noise" and decision.get("action") == "no_action"
                and all(abs(v) < 12 for v in group_changes)):
            losers = env.call("find_losers", {}).get("losers")
            if losers:
                seg = losers[0]
                conflicts.append(f"Growth Lead flagged dead audience '{seg['segment']}' "
                                 f"(ROAS {seg['recent_roas']}) to pause")
                decision = {"root_cause": "dead_campaign", "action": "pause_campaign",
                            "source_campaign": None, "target_campaign": None,
                            "rationale": f"[society] Pause dead audience '{seg['segment']}': {seg.get('why', '')}"}

        # --- Planner + Growth specialists (added) ---------------------------------
        # A real team doesn't stop at one lever. Unless the Analyst/Risk say HOLD or
        # FIX-TRACKING, the Portfolio Planner assembles every fix the account needs
        # and the Growth Lead adds any new-campaign opportunity — so when several
        # problems coincide the society delivers a PLAN, not a single move.
        if decision.get("action") not in ("no_action", "fix_tracking", "fix_landing_page",
                                          "pause_campaign", "decrease_budget"):
            plan = [{"group": it.get("group"), "action": it["action"]}
                    for it in env.call("recommend_portfolio", {})["items"]
                    if it["action"] != "no_action"]
            if len(plan) >= 2:
                launches = sum(1 for it in plan if it["action"] == "launch_campaign")
                conflicts.append(f"Planner proposed {len(plan)} coordinated actions"
                                 + (f" incl. {launches} new-campaign launch (Growth Lead)" if launches else ""))
                decision = {"root_cause": "multi", "action": "multi", "items": plan,
                            "source_campaign": None, "target_campaign": None,
                            "rationale": f"[society] Planner+Growth: a {len(plan)}-action plan."}

        total_tokens = sum(u.get("total_tokens", 0) for u in usage.values())
        transcript = {
            "scenario": env.scenario_id,
            "mode": "mock" if self.mock else "live",
            "final_decision": decision,
            "ruling_reason": result.reason,
            "conflict_detected": result.conflict_detected,
            "conflicts_resolved": len(conflicts),
            "conflicts": conflicts,
            "rounds": result.rounds,
            "models": {"analyst": MODELS["orchestrator"], "forecaster": MODELS["orchestrator"],
                       "risk": MODELS["cheap"], "coordinator": MODELS["synthesis"]},
            "usage": usage,
            "total_tokens": total_tokens,
            "latency_s": round(time.time() - t0, 2),
            "debate": result.transcript,
        }
        self._write_transcript(env.scenario_id, transcript)
        self.last_transcript = transcript
        return decision

    def _write_transcript(self, scenario_id, transcript):
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)
        with open(self.transcripts_dir / f"{scenario_id}.json", "w") as f:
            json.dump(transcript, f, indent=2)


def load_prompt(role):
    return (PROMPTS_DIR / f"{role}.md").read_text()


# ================================================================= live (LLM) specialists

def _parse_json_obj(content):
    if not content:
        return None
    try:
        i, j = content.index("{"), content.rindex("}") + 1
        return json.loads(content[i:j])
    except (ValueError, json.JSONDecodeError):
        return None


def _llm_specialist_call(role_prompt, schema_hint, env, model):
    """Run one specialist as a real Qwen tool-loop. Returns (json|None, usage, tools_used)."""
    from cmo.agents import PROBLEM
    from cmo.llm import BudgetExceeded, get_llm, tool_loop
    llm = get_llm(mock=False, model=model)
    sys = (role_prompt + "\n\nUse the tools to gather evidence, then reply with ONLY a "
           "JSON object (no markdown) of the form: " + schema_hint)
    msgs = [{"role": "system", "content": sys}, {"role": "user", "content": PROBLEM}]
    before = len(env.tool_log)
    try:
        content, _ = tool_loop(llm, env, msgs, tools=OPENAI_TOOL_SPECS, model=model)
    except BudgetExceeded:
        content = None
    tools_used = [e["tool"] for e in env.tool_log[before:]]
    return _parse_json_obj(content), llm.usage(), tools_used


def _f(val, default):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _funnel_refine(env, metrics, root):
    """Ground the diagnosis in the funnel decomposition (diagnose_drivers).

    The account distinguishes a creative problem (ctr collapse) from a targeting
    one (cvr collapse) on the SAME group, treats a cvr collapse with clicks intact
    as a tracking bug, and surfaces an under-invested audience as a launch — cuts a
    kind- or vibe-based read misses. Flag/macro diagnoses made upstream (learning,
    budget cap, seasonality, noise) are trusted and pass through untouched."""
    if root in ("learning_phase", "budget_cap", "seasonality", "noise"):
        return root
    changes = {cid: (d.get("roas_change_pct") or 0.0) for cid, d in metrics.items()}
    problem = min(changes, key=changes.get)
    if all(v > -6 for v in changes.values()):          # account looks flat -> look for an opportunity
        return "emerging_segment" if env.find_opportunities().get("opportunities") else root
    if problem == BRAND and changes[problem] < -8:      # the brand floor softened
        return "brand_demand_dip"
    if metrics[problem].get("flags"):
        return root
    d = env.diagnose_drivers(problem)["drivers"]
    ctr_drop, cvr_drop = 1 - d["creative"]["ratio"], 1 - d["targeting"]["ratio"]
    if cvr_drop >= 0.5 and ctr_drop < 0.15:
        return "tracking_outage"
    if cvr_drop >= 0.10 and cvr_drop > ctr_drop:
        return "audience_saturation"
    if ctr_drop >= 0.10:
        return "creative_fatigue"
    return root


def live_specialists(env, metrics):
    """Analyst + Forecaster are REAL Qwen calls; Risk is a deterministic tool check;
    the Coordinator (society_ruling) stays a coded policy. Any unparseable model
    output falls back to the mock brain so a live demo never crashes.
    Returns (analyst, forecaster, risk, usage)."""
    usage = {}

    # --- Analyst (LLM): diagnose the root cause ---
    a_json, a_use, a_tools = _llm_specialist_call(
        load_prompt("analyst"),
        '{"root_cause": "<one label>", "confidence": 0.0-1.0, "rationale": "<one sentence>"}',
        env, MODELS["orchestrator"])
    usage["analyst"] = a_use
    if a_json and a_json.get("root_cause"):
        root = a_json["root_cause"]
        a_conf, a_why = _f(a_json.get("confidence"), 0.8), a_json.get("rationale", "")
    else:  # fallback to the deterministic diagnostician
        root, _ = analyst_diagnose(metrics)
        a_conf, a_why = 0.75, f"(fallback) diagnosis = {root}"
    root = _funnel_refine(env, metrics, root)          # ground it in the funnel evidence
    analyst = Message(agent="Analyst", claim={"root_cause": root, "action": _implied_action(root)},
                      evidence=a_tools or ["get_campaign_metrics"], confidence=a_conf,
                      rationale=a_why or f"diagnosis = {root}")

    # --- Forecaster (LLM): propose the best move ---
    f_json, f_use, f_tools = _llm_specialist_call(
        load_prompt("forecaster"),
        '{"action":"shift_budget|increase_budget","source_campaign":"C#","target_campaign":"C#",'
        '"shift_pct":0-20,"confidence":0.0-1.0,"rationale":"<one sentence>"}',
        env, MODELS["orchestrator"])
    usage["forecaster"] = f_use
    valid_ids = set(GROUP_IDS)
    if (f_json and f_json.get("source_campaign") in valid_ids
            and f_json.get("target_campaign") in valid_ids):
        action = f_json.get("action") or "shift_budget"
        source, target = f_json["source_campaign"], f_json["target_campaign"]
        shift = min(20, max(1, int(_f(f_json.get("shift_pct"), 20))))
        f_conf, f_why = _f(f_json.get("confidence"), 0.7), f_json.get("rationale", "")
    else:  # fallback to the deterministic planner
        action, source, target = forecaster_plan(root, metrics)
        shift, f_conf, f_why = 20, 0.65, "(fallback) planner move"
    forecaster = Message(
        agent="Forecaster",
        claim={"root_cause": root, "action": action, "source_campaign": source,
               "target_campaign": target, "shift_pct": shift},
        evidence=f_tools or [f"forecast_roas:{source}->{target}"], confidence=f_conf,
        rationale=f_why or f"move {shift}% {source}->{target}")

    # --- Risk (deterministic tool check) ---
    risk = _risk_message(env, root, action, source, target)
    return analyst, forecaster, risk, usage
