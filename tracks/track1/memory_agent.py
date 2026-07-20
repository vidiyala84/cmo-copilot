"""H1-3 — MemoryAgent wrapper + memory-aware base agent (Track 1).

The mechanism (sanctioned by the PRD, not a hack): the same agent improves
across sessions because memory carries what it learned from **human corrections**
and from **the observed outcomes of its own past decisions**.

  - pre-decide: retrieve relevant memories (bounded context) + always inject
    standing preferences, and hand them to the base agent.
  - decide: the base agent starts from the naive `heuristic_diagnose` baseline,
    then lets memory override it:
      * a preference ("never move budget out of brand C2") blocks a bad action;
      * an outcome precedent for the *same situation signature* — either a past
        success to repeat, or enough past backfires to finally change course.
  - post-decide: write an episode.
  - after the outcome is scored: write an outcome memory (worked / backfired).
    A backfire records what actually turned out to be correct, so a later
    session facing the same signature can adopt it.

"Reluctance" models honest caution: relabelling a root cause takes 1 bad
outcome, switching to patience (no_action) takes 2, switching to *increase*
takes 3. That is what turns the accuracy curve into a climb rather than a step.
"""
import json
from typing import List, Optional

from cmo.agents import heuristic_diagnose
from tracks.track1.memory_store import Memory, MemoryStore
from tracks.track1.retriever import Retriever

DECISION_FIELDS = ("root_cause", "action", "source_campaign", "target_campaign", "shift_pct")


# ----------------------------------------------------------------- helpers

def _payload(m: Memory) -> dict:
    if not m.payload:
        return {}
    try:
        return json.loads(m.payload)
    except json.JSONDecodeError:
        return {}


def _decision_core(decision: dict) -> dict:
    return {k: decision.get(k) for k in DECISION_FIELDS}


def _merge_decision(base: dict, recalled: dict) -> dict:
    d = dict(base)
    for k in DECISION_FIELDS:
        if k in recalled:
            d[k] = recalled[k]
    return d


def _rate_ratio(recent: dict, prior: dict, key: str) -> float:
    p = prior.get(key) or 0
    return (recent.get(key, 0) / p) if p else 1.0


def _perday_ratio(recent: dict, prior: dict, key: str, rd=14, pd=76) -> float:
    p = (prior.get(key) or 0) / pd
    r = (recent.get(key) or 0) / rd
    return (r / p) if p else 1.0


def situation_signature(metrics: dict, opportunities: dict = None):
    """A stable, observable descriptor of the situation — same across sessions
    for a given scenario, distinct across scenarios. Never keyed on scenario id.

    `opportunities` is a `find_opportunities` result and is not optional in
    practice, only in signature. Group metrics alone cannot separate an emerging
    audience from plain noise: a segment worth launching against is ~3% of one
    group's spend, so at group level S11 and S10 are the same reading. Without
    the segment axis the memory keys collide and a "do nothing" correction
    learned on noise gets retrieved for a live opportunity.
    """
    changes = {cid: (d.get("roas_change_pct") or 0.0) for cid, d in metrics.items()}
    flags_all = {cid: d.get("flags") or {} for cid, d in metrics.items() if d.get("flags")}
    problem = min(changes, key=changes.get)
    best = max(changes, key=changes.get)
    vals = list(changes.values())
    mean = sum(vals) / len(vals)
    spread = max(vals) - min(vals)

    tokens = []
    for cid, fl in sorted(flags_all.items()):
        if "last_edited_days_ago" in fl:
            tokens.append(f"flag_learning_phase_{cid}")
        if "lost_impression_share_budget_pct" in fl:
            tokens.append(f"flag_budget_cap_{cid}")

    if all(abs(v) < 12 for v in vals):
        tokens.append("all_within_noise")
    elif mean < -15 and spread < 16:
        tokens.append("broad_uniform_decline")

    # The segment axis — invisible in `metrics`, and the only thing separating an
    # emerging audience from a quiet week.
    for opp in (opportunities or {}).get("opportunities", [])[:1]:
        tokens.append("segment_surge_" + opp["segment"].replace(" ", "_"))

    pm = metrics[problem]
    recent, prior = pm["recent_14d"], pm["prior_76d"]
    if _perday_ratio(recent, prior, "conversions") < 0.4 and _perday_ratio(recent, prior, "clicks") > 0.85:
        tokens.append(f"tracking_collapse_{problem}")
    if _rate_ratio(recent, prior, "ctr") < 0.8:
        tokens.append(f"ctr_down_{problem}")
    if _rate_ratio(recent, prior, "cvr") < 0.8:
        tokens.append(f"cvr_down_{problem}")
    if _perday_ratio(recent, prior, "clicks") < 0.8:
        tokens.append(f"clicks_down_{problem}")
    if best != problem and changes[best] > 15:
        tokens.append(f"winner_{best}")
    tokens.append(f"problem_{problem}")
    return " ".join(sorted(set(tokens))), problem


def expected_to_decision(expected: dict) -> dict:
    """What actually turned out to be correct — the outcome monitor's ground truth."""
    action = expected["action"]
    target = expected["acceptable_targets"][0] if expected.get("acceptable_targets") else None
    source = expected["acceptable_sources"][0] if expected.get("acceptable_sources") else None
    shift = 15 if action in ("shift_budget", "increase_budget") else None
    return {"root_cause": expected["root_cause"], "action": action,
            "source_campaign": source, "target_campaign": target, "shift_pct": shift}


def reluctance(taken_action: Optional[str], correct_action: str) -> int:
    if correct_action == taken_action:
        return 1                      # only relabelling the root cause
    if correct_action == "no_action":
        return 2                      # switching to patience
    if correct_action == "increase_budget":
        return 3                      # switching to spend *more*
    return 1


# ----------------------------------------------------------------- base agents

def apply_memory_overrides(base: dict, memories, signature, problem):
    """Layer recalled memory on top of ANY base decision. Returns (decision, reasons).
    Reusable so memory can wrap the heuristic, a single Qwen agent, OR the society."""
    d, reasons = dict(base), []

    # (1) standing preferences (enforced, not suggested)
    for m in memories or []:
        if m.kind != "preference":
            continue
        rule = _payload(m)
        cap = rule.get("max_shift_pct")
        if cap is not None and d.get("shift_pct") and d["shift_pct"] > cap:
            d["shift_pct"] = cap
            reasons.append(f"capped shift to {cap}% (preference)")
        fs = rule.get("forbid_source")
        if fs and d.get("source_campaign") == fs:
            if rule.get("problem_campaign") == problem and rule.get("set"):
                d.update(rule["set"])
                d["source_campaign"] = d["target_campaign"] = d["shift_pct"] = None
                reasons.append(f"{fs} is protected brand -> {d['action']} (preference)")
            else:
                d.update({"action": "no_action", "source_campaign": None,
                          "target_campaign": None, "shift_pct": None})
                reasons.append(f"refused to source protected {fs} -> hold")

    # (2) outcome precedents for the exact same situation
    outs = [m for m in (memories or []) if m.kind == "outcome" and m.topic == signature]
    worked = [m for m in outs if m.polarity > 0]
    backfired = [m for m in outs if m.polarity < 0]
    if worked:
        pay = _payload(max(worked, key=lambda m: m.outcome_weight))
        if pay.get("decision"):
            d = _merge_decision(d, pay["decision"])
            reasons.append("repeated a past success (outcome memory)")
    elif backfired:
        need = _payload(backfired[0]).get("reluctance", 1)
        if len(backfired) >= need:
            pay = _payload(backfired[0])
            if pay.get("correct"):
                d = _merge_decision(d, pay["correct"])
                reasons.append(f"changed course after {len(backfired)} backfires")

    if reasons:
        d["rationale"] = base.get("rationale", "") + " | memory: " + "; ".join(reasons)
    return d, reasons


class MemoryAwareHeuristicAgent:
    """Mock base agent: naive heuristic + memory overrides. Offline, deterministic."""
    name = "memory-heuristic"

    def decide(self, env, memories: Optional[List[Memory]] = None, metrics=None,
               signature=None, problem=None):
        base = heuristic_diagnose(env)
        if metrics is None:
            metrics = env.call("get_campaign_metrics", {})
        if signature is None:
            signature, problem = situation_signature(metrics, env.call("find_opportunities", {}))
        d, reasons = apply_memory_overrides(base, memories, signature, problem)
        self.last_trace = {"baseline": _decision_core(base), "memory_moves": list(reasons)}
        return d


class MemorySocietyAgent:
    """Memory + Society: the 4-agent society decides, then memory enforces recalled
    preferences and corrects situations that backfired before. Learns across sessions."""
    name = "memory-society"

    def __init__(self, mock=True, transcripts_dir=None):
        from tracks.track3.society import SocietyAgent
        self.society = SocietyAgent(mock=mock, transcripts_dir=transcripts_dir)
        self.last_trace = {}

    def decide(self, env, memories: Optional[List[Memory]] = None, metrics=None,
               signature=None, problem=None):
        base = self.society.decide(env)              # the full society debate
        if metrics is None:
            metrics = env.call("get_campaign_metrics", {})
        if signature is None:
            signature, problem = situation_signature(metrics, env.call("find_opportunities", {}))
        d, reasons = apply_memory_overrides(base, memories, signature, problem)
        self.last_trace = {"baseline": _decision_core(base), "memory_moves": list(reasons)}
        return d


class MemoryAwareQwenAgent:
    """Live base agent: injects the recalled memory block into the prompt, then
    runs the shared Qwen tool loop. Not exercised in mock CI (needs a key)."""
    name = "memory-qwen"

    def __init__(self, llm=None, model=None, max_tool_calls=8):
        from cmo.llm import default_live_llm
        self.llm = llm or default_live_llm(model=model)
        self.model = model
        self.max_tool_calls = max_tool_calls

    def decide(self, env, memories=None, metrics=None, signature=None, problem=None):
        import json as _json
        from cmo.agents import PROBLEM, QwenBaselineAgent
        from cmo.config import DECISION_SCHEMA_HINT
        from cmo.llm import BudgetExceeded, over_budget_decision, tool_loop
        from cmo.tools import OPENAI_TOOL_SPECS
        block = "\n".join(f"- {m.text}" for m in (memories or [])) or "(no prior memories)"
        self.llm.reset()
        sys = ("You are a marketing budget analyst with MEMORY of past sessions.\n"
               "Recalled memories (respect preferences; weigh past outcomes):\n" + block +
               "\n\nUse the tools to diagnose, then reply with ONLY a JSON object matching:\n"
               + _json.dumps(DECISION_SCHEMA_HINT, indent=2) +
               "\nValidate shifts with propose_reallocation. Never move budget when the "
               "right fix is tracking repair or patience.")
        msgs = [{"role": "system", "content": sys}, {"role": "user", "content": PROBLEM}]
        try:
            content, _ = tool_loop(self.llm, env, msgs, tools=OPENAI_TOOL_SPECS,
                                   model=self.model, max_tool_calls=self.max_tool_calls)
        except BudgetExceeded as e:
            return over_budget_decision(e.used, e.cap)
        return QwenBaselineAgent._parse(content)


# ----------------------------------------------------------------- wrapper

class MemoryAgent:
    """Wraps any base agent with recall (pre-decide) and writing (post-decide +
    post-outcome). `session` is set by the runner before each pass."""

    def __init__(self, base_agent, store: MemoryStore, retriever: Retriever):
        self.base = base_agent
        self.store = store
        self.retriever = retriever
        self.name = f"memory({base_agent.name})"
        self._context = {}          # scenario_id -> (signature, problem)
        self.last_context_tokens = 0
        self.last_injected: List[Memory] = []
        self.last_trace = {}
        self.last_outcome = ""

    def _inject(self, signature: str, session: int) -> List[Memory]:
        res = self.retriever.retrieve(signature, current_session=session)
        prefs = [m for m in self.store.list_active() if m.kind == "preference"]
        seen, injected = set(), []
        for m in prefs + res.memories:      # preferences always injected, first
            if m.id not in seen:
                seen.add(m.id)
                injected.append(m)
        self.last_context_tokens = res.used_tokens + sum(
            max(1, len(p.text) // 4) for p in prefs)
        self.last_injected = injected
        return injected

    def decide(self, env, session: int):
        metrics = env.call("get_campaign_metrics", {})
        signature, problem = situation_signature(metrics, env.call("find_opportunities", {}))
        injected = self._inject(signature, session)
        decision = self.base.decide(env, memories=injected, metrics=metrics,
                                    signature=signature, problem=problem)
        self.store.add("episode",
                       f"S{session} [{signature}] -> {decision['root_cause']}/{decision['action']}",
                       session=session, campaign_id=problem, topic=signature,
                       outcome_weight=0.5,
                       payload=json.dumps({"decision": _decision_core(decision)}))
        self._context[env.scenario_id] = (signature, problem)

        base_trace = getattr(self.base, "last_trace", {})
        self.last_trace = {
            "signature": signature,
            "recalled": [{"kind": m.kind, "text": m.text} for m in injected],
            "baseline": base_trace.get("baseline"),
            "memory_moves": base_trace.get("memory_moves", []),
            "final": _decision_core(decision),
        }
        return decision

    def record_outcome(self, env, scenario, decision, score: float, session: int):
        signature, problem = self._context.get(env.scenario_id, (None, None))
        if signature is None:
            signature, problem = situation_signature(env.call("get_campaign_metrics", {}),
                                                     env.call("find_opportunities", {}))
        if score >= 0.8:
            self.store.add(
                "outcome", f"[{signature}] '{decision['action']}' worked (score {score:.1f}).",
                session=session, campaign_id=problem, topic=signature, polarity=+1,
                outcome_weight=1.0, confidence=score,
                payload=json.dumps({"decision": _decision_core(decision), "score": score}))
            self.last_outcome = (f"scored {score:.1f} → wrote a “worked” memory "
                                 f"(reinforces this decision for next session)")
        elif score <= 0.4:
            correct = expected_to_decision(scenario["expected"])
            self.store.add(
                "outcome",
                f"[{signature}] '{decision['action']}' backfired (score {score:.1f}); "
                f"correct was {correct['root_cause']}/{correct['action']}.",
                session=session, campaign_id=problem, topic=signature, polarity=-1,
                outcome_weight=1.0, confidence=1 - score,
                payload=json.dumps({"taken": _decision_core(decision), "correct": correct,
                                    "reluctance": reluctance(decision.get("action"),
                                                             correct["action"])}))
            self.last_outcome = (f"scored {score:.1f} → wrote a “backfired” memory "
                                 f"(learned the correct answer is {correct['root_cause']}/{correct['action']})")
        else:
            self.last_outcome = f"scored {score:.1f} → no strong memory written (ambiguous)"


# ----------------------------------------------------------------- corrections

def load_corrections(path=None):
    from cmo.config import ROOT
    path = path or (ROOT / "tracks" / "track1" / "corrections.json")
    with open(path) as f:
        return json.load(f)


def apply_corrections(store: MemoryStore, corrections, after_session: int) -> int:
    """Apply any user corrections scheduled for this session. Returns count applied."""
    n = 0
    for c in corrections:
        if c.get("after_session") != after_session:
            continue
        store.add(c["kind"], c["text"], session=after_session,
                  campaign_id=c.get("campaign_id"), topic=c.get("topic"),
                  confidence=c.get("confidence", 1.0),
                  payload=json.dumps(c["payload"]) if c.get("payload") else None)
        n += 1
    return n
