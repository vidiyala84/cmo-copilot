"""Two baseline agents.

MockHeuristicAgent — offline, rule-based. Exists to prove the harness plumbing
and to embody the 'naive baseline' the tracks must beat. It is *supposed* to
fail the trap scenarios (S07 brand floor, S08 learning phase, S09 budget cap).

QwenBaselineAgent — single-shot tool-calling agent on Qwen (OpenAI-compatible
API), via the shared `llm.QwenLLM` client. Needs a DASHSCOPE_API_KEY. This is
the official baseline: no memory, no sub-agents, no execution.
"""
import json
from cmo.config import DECISION_SCHEMA_HINT
from cmo.portfolio import account_brief
from cmo.tools import OPENAI_TOOL_SPECS

PROBLEM = (f"Campaign performance dropped this week across {account_brief()}. "
           "Diagnose the root cause and decide: reallocate budget, increase a budget, "
           "fix tracking, or do nothing.")


def heuristic_diagnose(env):
    """The naive rule-based diagnosis. Shared by MockHeuristicAgent and Track 1's
    memory-aware base agent so both start from the identical baseline. It is
    *supposed* to walk into the trap scenarios (S07/S08/S09)."""
    m = env.call("get_campaign_metrics", {})
    deltas, stats = {}, {}
    for cid, d in m.items():
        prior, recent = d["prior_76d"], d["recent_14d"]
        deltas[cid] = (recent["roas"] / prior["roas"] - 1) * 100 if prior["roas"] else 0
        stats[cid] = d

    # tracking check: conversions collapsed while clicks held
    for cid, d in stats.items():
        conv_ratio = (d["recent_14d"]["conversions"] / 14) / max(d["prior_76d"]["conversions"] / 76, 1e-9)
        click_ratio = (d["recent_14d"]["clicks"] / 14) / max(d["prior_76d"]["clicks"] / 76, 1e-9)
        if conv_ratio < 0.4 and click_ratio > 0.85:
            return {"root_cause": "tracking_outage", "action": "fix_tracking",
                    "source_campaign": None, "target_campaign": None, "shift_pct": None,
                    "rationale": f"{cid} conversions at {conv_ratio:.0%} of norm while clicks held."}

    vals = list(deltas.values())
    mean_d = sum(vals) / len(vals)
    spread = max(vals) - min(vals)
    if mean_d < -15 and spread < 16:
        return {"root_cause": "seasonality", "action": "no_action",
                "source_campaign": None, "target_campaign": None, "shift_pct": None,
                "rationale": "Uniform decline across all campaigns."}
    if all(abs(v) < 12 for v in vals):
        return {"root_cause": "noise", "action": "no_action",
                "source_campaign": None, "target_campaign": None, "shift_pct": None,
                "rationale": "All movements inside normal variance."}

    # naive: worst delta = source, best recent ROAS = target. Falls into every trap.
    source = min(deltas, key=deltas.get)
    best_up = max(deltas, key=deltas.get)
    target = max((c for c in stats if c != source),
                 key=lambda c: stats[c]["recent_14d"]["roas"])
    src = stats[source]
    ctr_ratio = src["recent_14d"]["ctr"] / max(src["prior_76d"]["ctr"], 1e-9)
    cvr_ratio = src["recent_14d"]["cvr"] / max(src["prior_76d"]["cvr"], 1e-9)
    if deltas[best_up] > 15 and abs(deltas[source]) < 15:
        root, source = "winner_opportunity", min((c for c in deltas if c != best_up), key=deltas.get)
        target = best_up
    elif ctr_ratio < 0.78:
        root = "creative_fatigue"
    elif cvr_ratio < 0.78:
        root = "audience_saturation"
    else:
        root = "competitor_pressure"
    env.call("forecast_roas", {"source_campaign": source, "target_campaign": target, "shift_pct": 15})
    return {"root_cause": root, "action": "shift_budget",
            "source_campaign": source, "target_campaign": target, "shift_pct": 15,
            "rationale": f"{source} ROAS {deltas[source]:+.0f}%; {target} best recent ROAS."}


class MockHeuristicAgent:
    name = "mock-heuristic"

    def decide(self, env):
        return heuristic_diagnose(env)


class PlannerAgent:
    """Deterministic multi-item planner.

    Where the baseline names a single move, this turns the whole account into a
    PLAN — several fixes and any new-campaign launches — by calling the
    `recommend_portfolio` tool. The action space is derived from tool calls, not
    guessed by an LLM: the same account always yields the same plan and every
    item cites the number that produced it. Emits `items`, which routes the
    harness to plan (set-based) scoring.
    """
    name = "planner"

    def decide(self, env):
        plan = env.call("recommend_portfolio", {})
        return {
            "root_cause": "multi", "action": "multi", "items": plan["items"],
            "source_campaign": None, "target_campaign": None, "shift_pct": None,
            "rationale": plan["note"],
        }


class StructuredAgent:
    """Deterministic, tool-derived agent for BOTH single-action and plan questions.

    Calls `recommend_portfolio` and adapts its output shape: no items → no_action;
    one item → a single-action decision; several → a multi-item plan. It has no LLM
    and no notion of the *narrative* root cause, so on single-action questions it
    earns the action + sourcing points but not the root-cause point — a realistic
    'rules engine' that is strong on funnel fixes and plans, and blind to the traps
    (a cvr collapse from a tracking bug reads to it as a real targeting move)."""
    name = "structured"

    def decide(self, env):
        items = [{"group": i["group"], "action": i["action"]}
                 for i in env.recommend_portfolio()["items"] if i["action"] != "no_action"]
        if not items:
            return {"root_cause": "noise", "action": "no_action",
                    "source_campaign": None, "target_campaign": None, "items": []}
        if len(items) == 1:  # a single recommended action implies its diagnosis
            it = items[0]
            root = {"refresh_creative": "creative_fatigue", "fix_targeting": "audience_saturation",
                    "launch_campaign": "emerging_segment", "increase_budget": "budget_cap",
                    "fix_tracking": "tracking_outage"}.get(it["action"], "multi")
            return {"root_cause": root, "action": it["action"], "items": items,
                    "source_campaign": None, "target_campaign": it["group"]}
        return {"root_cause": "multi", "action": "multi", "items": items,
                "source_campaign": None, "target_campaign": None}


class GatedPlannerAgent:
    """The composition that wins all three tiers: a multi-item planner behind a
    deterministic risk/trap gate.

    The benchmark exposed a tension — planners ace fixes and plans but *over-act on
    the traps*; rules/veto handle the traps but *can't plan*. This does both. A
    trap gate runs first: when the evidence says DON'T reshuffle (a measurement
    bug, a uniform seasonal dip, the floor-protected brand softening, a
    learning-phase campaign, or plain noise) it returns the correct hold /
    fix-tracking / increase-on-cap. Only when there is a real, actionable problem
    does it fall through to the tool-derived plan — which handles a single fix, or
    several at once plus a launch. Fully deterministic and offline.
    """
    name = "gated-planner"
    BRAND = "G2"

    def decide(self, env):
        metrics = env.call("get_campaign_metrics", {})
        gate = self._trap_gate(env, metrics)
        return gate if gate is not None else StructuredAgent().decide(env)

    @classmethod
    def _trap_gate(cls, env, metrics):
        def hold(root, action="no_action", target=None):
            return {"root_cause": root, "action": action, "items": [],
                    "source_campaign": None, "target_campaign": target}

        changes = {cid: (d.get("roas_change_pct") or 0.0) for cid, d in metrics.items()}
        # 1. flags are whole-group verdicts the funnel can't see
        for cid, d in metrics.items():
            fl = d.get("flags") or {}
            if "last_edited_days_ago" in fl:
                return hold("learning_phase")                      # patience
            if "lost_impression_share_budget_pct" in fl:
                return hold("budget_cap", "increase_budget", target=cid)
        # 2. conversions collapse while clicks hold — pixel, page, or downstream leak?
        for cid in metrics:
            d = env.diagnose_drivers(cid)["drivers"]
            conv_drop = 1 - d["targeting"]["ratio"]
            creative_drop = 1 - d["creative"]["ratio"]
            bounce_ratio = d["landing"]["ratio"]        # recent/prior bounce_rate
            aov_ratio = d["offer_mix"]["ratio"]
            if conv_drop >= 0.35 and creative_drop < 0.15 and bounce_ratio >= 1.4:
                return hold("landing_page_break", "fix_landing_page")  # bounce spiked -> page break
            if conv_drop >= 0.5 and creative_drop < 0.15 and bounce_ratio < 1.25:
                return hold("tracking_outage", "fix_tracking")         # bounce flat -> pixel
            if changes[cid] < -12 and aov_ratio < 0.75 and creative_drop < 0.15 and conv_drop < 0.15:
                return hold("funnel_leak")                             # ads fine, value leaks downstream
        # 2b. over-investment: spend ramped, ROAS fell, frequency climbed -> pull back
        for cid, d in metrics.items():
            if (d.get("roas_change_pct") or 0.0) >= -10:
                continue
            r, p = d["recent_14d"], d["prior_76d"]
            spend_r = (r["spend"] / 14) / max(p["spend"] / 76, 1e-9)
            freq_r = (r.get("frequency") or 0.0) / max(p.get("frequency") or 1e-9, 1e-9)
            cvr_r = (r["cvr"] or 0.0) / max(p["cvr"] or 1e-9, 1e-9)
            if spend_r > 1.2 and freq_r > 1.15 and cvr_r < 0.92:
                return hold("over_saturation", "decrease_budget", target=cid)
        vals = list(changes.values())
        # 3. everything down together = seasonality
        if all(v < -8 for v in vals):
            return hold("seasonality")
        # 4. the worst mover is the floor-protected brand group
        worst = min(changes, key=changes.get)
        if worst == cls.BRAND and changes[worst] < -8:
            return hold("brand_demand_dip")
        # 4b. a structurally dead audience — kill it (only when the account is otherwise
        #     quiet at group level, so a heavily-cratered group can't masquerade as one)
        if all(abs(v) < 12 for v in vals) and env.find_losers().get("losers"):
            return hold("dead_campaign", "pause_campaign")
        # 5. a real opportunity in an otherwise quiet account -> let the plan launch
        if env.find_opportunities().get("opportunities"):
            return None
        # 6. nothing moved materially = noise
        if all(abs(v) < 6 for v in vals):
            return hold("noise")
        return None                                                # a real problem -> plan


class QwenBaselineAgent:
    name = "qwen-baseline"

    def __init__(self, llm=None, model=None, max_tool_calls=8):
        from cmo.llm import default_live_llm  # lazy: keeps mock-only runs import-light
        self.llm = llm or default_live_llm(model=model)
        self.model = model
        self.max_tool_calls = max_tool_calls

    def decide(self, env):
        from cmo.llm import BudgetExceeded, over_budget_decision, tool_loop
        self.llm.reset()
        sys = ("You are a marketing budget analyst. Use the tools to diagnose, then reply "
               "with ONLY a JSON object matching this schema (no markdown):\n"
               + json.dumps(DECISION_SCHEMA_HINT, indent=2)
               + "\nRules: validate any shift with propose_reallocation before deciding; "
                 "if it returns violations, change your plan. Never move budget when the "
                 "correct fix is tracking repair or patience. Every number in the rationale "
                 "must come from a tool result.")
        msgs = [{"role": "system", "content": sys}, {"role": "user", "content": PROBLEM}]
        try:
            content, _ = tool_loop(self.llm, env, msgs, tools=OPENAI_TOOL_SPECS,
                                   model=self.model, max_tool_calls=self.max_tool_calls)
        except BudgetExceeded as e:
            return over_budget_decision(e.used, e.cap)
        return self._parse(content)

    @staticmethod
    def _parse(content):
        fallback = {"root_cause": "noise", "action": "no_action", "source_campaign": None,
                    "target_campaign": None, "shift_pct": None, "rationale": "parse failure"}
        if not content:
            return fallback
        try:
            start, end = content.index("{"), content.rindex("}") + 1
            d = json.loads(content[start:end])
            return {**fallback, **d}
        except (ValueError, json.JSONDecodeError):
            return fallback


PLAN_SCHEMA_HINT = (
    '{"items": [{"group": "G1..G5, or null for a brand-new campaign", '
    '"action": "refresh_creative | fix_targeting | launch_campaign | increase_budget | '
    'decrease_budget | shift_budget"}], "rationale": "<2-3 sentences, numbers from tools>"}')

PROBLEM_PLAN = ("Campaign performance moved this week across the account. Produce the FULL set of "
                "actions to take this week — there may be several across different campaigns, or none.")


class PlannerLLMAgent:
    """An LLM that produces a MULTI-ITEM plan by reasoning over the tools.

    Unlike the single-shot baseline, it is told a reallocation is often several
    moves at once — a group can need both a creative refresh (ctr fell) AND a
    targeting fix (cvr fell), and a surging audience may deserve its own campaign.
    It diagnoses every group and emits a plan. Output shape adapts so it scores on
    every tier: empty → no_action, one item → single action, many → a plan.
    """
    name = "planner-llm"

    def __init__(self, llm=None, model=None, max_tool_calls=12):
        from cmo.llm import default_live_llm
        self.llm = llm or default_live_llm(model=model)
        self.model = model
        self.max_tool_calls = max_tool_calls

    def decide(self, env):
        from cmo.llm import BudgetExceeded, tool_loop
        self.llm.reset()
        sys = ("You are a marketing portfolio planner. A campaign reallocation is often NOT one move: a "
               "group can need BOTH a creative refresh (its click-through fell) AND a targeting fix (its "
               "conversion rate fell), and an under-invested audience that is outperforming deserves a "
               "brand-new campaign. Use the tools to diagnose EVERY group (diagnose_drivers), scan for "
               "launch opportunities (find_opportunities); recommend_portfolio assembles a candidate plan "
               "you may adopt or adjust. Then reply with ONLY a JSON object (no markdown):\n"
               + PLAN_SCHEMA_HINT +
               "\nRules: include an item ONLY for a real, evidenced problem or opportunity; a healthy group "
               "contributes nothing (empty list is valid); never move budget out of the brand group G2; "
               "use group=null with action launch_campaign for a new campaign.")
        msgs = [{"role": "system", "content": sys}, {"role": "user", "content": PROBLEM_PLAN}]
        try:
            content, _ = tool_loop(self.llm, env, msgs, tools=OPENAI_TOOL_SPECS,
                                   model=self.model, max_tool_calls=self.max_tool_calls)
        except BudgetExceeded:
            return {"root_cause": "noise", "action": "no_action", "items": []}
        return self._to_decision(content)

    @staticmethod
    def _to_decision(content):
        items, seen = [], set()
        try:
            i, j = content.index("{"), content.rindex("}") + 1
            for it in json.loads(content[i:j]).get("items", []):
                action = it.get("action")
                if not action or action == "no_action":
                    continue
                g = it.get("group")
                g = None if g in (None, "", "null", "NEW", "new") or action == "launch_campaign" else g
                if (g, action) not in seen:
                    seen.add((g, action))
                    items.append({"group": g, "action": action})
        except (ValueError, json.JSONDecodeError, AttributeError, TypeError):
            items = []
        if not items:
            return {"root_cause": "noise", "action": "no_action",
                    "source_campaign": None, "target_campaign": None, "items": []}
        if len(items) == 1:  # a single recommended action implies its diagnosis
            it = items[0]
            root = {"refresh_creative": "creative_fatigue", "fix_targeting": "audience_saturation",
                    "launch_campaign": "emerging_segment", "increase_budget": "budget_cap",
                    "fix_tracking": "tracking_outage"}.get(it["action"], "multi")
            return {"root_cause": root, "action": it["action"], "items": items,
                    "source_campaign": None, "target_campaign": it["group"]}
        return {"root_cause": "multi", "action": "multi", "items": items,
                "source_campaign": None, "target_campaign": None}


# ---------------------------------------------------------------------------
# The "layman" control: just ask Qwen directly, no tools, no structure.
# ---------------------------------------------------------------------------

def describe_account(metrics):
    """Plain-language dashboard summary — what a business owner would paste into a chat."""
    lines = ["Here's my ad account this week (recent 14 days vs the prior period):"]
    for cid, d in metrics.items():
        r, p = d["recent_14d"], d["prior_76d"]
        ch = d.get("roas_change_pct")
        chs = f"{ch:+.0f}%" if ch is not None else "n/a"
        line = (f"- {d['name']} [{cid}] ({d['kind']} on {d['platform']}): "
                f"ROAS {r['roas']} (was {p['roas']}, {chs}); CTR {r['ctr']}, CVR {r['cvr']}, "
                f"about ${r['daily_spend']}/day.")
        fl = d.get("flags") or {}
        if "last_edited_days_ago" in fl:
            line += f" Note: this campaign was rebuilt {fl['last_edited_days_ago']} days ago."
        if "lost_impression_share_budget_pct" in fl:
            line += f" Note: losing {fl['lost_impression_share_budget_pct']}% impression share to budget caps."
        lines.append(line)
    return "\n".join(lines)


DIRECT_SYS = ("You are a helpful marketing assistant. A small-business owner pastes their "
              "dashboard and asks what to do about their budget. Give your best recommendation.")

# The full "expert brief" — every business rule + diagnostic tell the society's
# specialists know, handed to the model directly in the prompt. No tools, no
# structure: this isolates whether just TELLING the model the rules is enough.
RULES_BRIEF = """
IMPORTANT — the account's business rules and diagnostic playbook (apply them):
Business constraints:
  1. Brand campaign C2 monthly spend must NEVER fall below $2,000. Do not source budget from C2 if it would breach this.
  2. Never move more than 20% of a campaign's budget in a single week.
  3. A campaign rebuilt/edited within the last 7 days is in its LEARNING PHASE — do not touch it; its numbers are noisy. Wait.
Diagnostic playbook:
  4. If conversions collapse but CLICKS HOLD steady, that's a TRACKING BUG, not a real drop — the fix is fix_tracking, NOT moving budget.
  5. If ALL campaigns are down together, it's SEASONALITY — hold (no_action), don't reallocate.
  6. If the losing campaign IS the brand campaign (C2) and clicks are simply down, that's a BRAND DEMAND DIP (external) — hold.
  7. If a campaign is winning but flagged as losing impression share to BUDGET CAPS, the fix is increase_budget on it, not a shift.
  8. If changes are all small (within ~12%), it's NOISE — do nothing.
"""


def naive_direct_decision(metrics):
    """Offline stand-in for generic-LLM advice: catches the obvious flat/uniform
    cases, otherwise defaults to 'cut the worst, feed the best' and walks into the traps."""
    changes = {cid: (d.get("roas_change_pct") or 0.0) for cid, d in metrics.items()}
    vals = list(changes.values())
    mean = sum(vals) / len(vals)
    spread = max(vals) - min(vals)
    if all(abs(v) < 12 for v in vals):
        return {"root_cause": "noise", "action": "no_action", "source_campaign": None,
                "target_campaign": None, "shift_pct": None, "rationale": "Looks like normal fluctuation."}
    if mean < -18 and spread < 20:
        return {"root_cause": "seasonality", "action": "no_action", "source_campaign": None,
                "target_campaign": None, "shift_pct": None, "rationale": "Everything's down — probably seasonal."}
    worst = min(changes, key=changes.get)
    recent_roas = {cid: metrics[cid]["recent_14d"]["roas"] for cid in metrics}
    target = max((c for c in metrics if c != worst), key=lambda c: recent_roas[c])
    return {"root_cause": "creative_fatigue", "action": "shift_budget",
            "source_campaign": worst, "target_campaign": target, "shift_pct": 20,
            "rationale": f"{worst} is underperforming; move budget to your best performer {target}."}


class DirectQwenAgent:
    """No tools, no validation, no structure — the dashboard described in words +
    the question, one shot to the model. Exactly what you get pasting numbers into
    ChatGPT/Qwen and asking 'what should I do?'."""
    name = "direct-qwen"

    def __init__(self, llm=None, mock=False, model=None, with_rules=False):
        self.mock = mock
        self._llm = llm
        self.model = model
        self.with_rules = with_rules   # give Qwen the business rules directly in the prompt
        self.last_tokens = {}

    def decide(self, env):
        metrics = env.call("get_campaign_metrics", {})
        if self.mock:
            return naive_direct_decision(metrics)
        from cmo.llm import BudgetExceeded, default_live_llm, over_budget_decision
        llm = self._llm or default_live_llm(model=self.model)
        self._llm = llm
        llm.reset()
        sys = DIRECT_SYS + (RULES_BRIEF if self.with_rules else "")
        user = (describe_account(metrics) + "\n\n" + PROBLEM +
                "\n\nReply with ONLY a JSON object (no markdown):\n"
                + json.dumps(DECISION_SCHEMA_HINT, indent=2))
        try:
            msg = llm.complete([{"role": "system", "content": sys},
                                {"role": "user", "content": user}])  # NO tools
        except BudgetExceeded as e:
            return over_budget_decision(e.used, e.cap)
        self.last_tokens = llm.usage()
        return QwenBaselineAgent._parse(msg.content)
