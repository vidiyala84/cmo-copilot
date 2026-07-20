"""H2-1 — structured negotiation protocol (Track 3).

Not free-form chat. Every specialist submits a `Message(agent, claim, evidence,
confidence)`. A conflict detector (contradictory claims, an action disagreement,
or a Risk veto) triggers a bounded debate — at most 2 rebuttal rounds — after
which the Coordinator rules with an explicit, coded policy:

    1. A Risk-Officer constraint objection is an ABSOLUTE veto.
    2. Otherwise prefer the claim whose evidence cites more tool results.
    3. Tie on evidence -> higher confidence wins.
    4. Still tied (and the claims genuinely conflict) -> conservative default
       (no_action).

All pure logic — no LLM here, so the ruling is deterministic and unit-tested.
"""
from dataclasses import dataclass, field
from typing import Callable, List, Optional

DECISION_FIELDS = ("root_cause", "action", "source_campaign", "target_campaign", "shift_pct")

NO_ACTION = {"root_cause": "noise", "action": "no_action",
             "source_campaign": None, "target_campaign": None, "shift_pct": None}


@dataclass
class Message:
    agent: str
    claim: dict                              # partial/whole decision proposal
    evidence: List[str] = field(default_factory=list)   # tool refs, e.g. "forecast_roas:C4->C5"
    confidence: float = 0.5
    rationale: str = ""
    veto: Optional[str] = None               # Risk sets a reason here to object
    veto_override: Optional[dict] = None      # claim to adopt when the veto wins

    def to_dict(self):
        return {"agent": self.agent, "claim": self.claim, "evidence": self.evidence,
                "confidence": self.confidence, "rationale": self.rationale,
                "veto": self.veto, "veto_override": self.veto_override}


@dataclass
class DebateResult:
    ruling: dict
    reason: str
    rounds: int
    conflict_detected: bool
    transcript: List[dict] = field(default_factory=list)


# ----------------------------------------------------------------- conflict

def claims_conflict(a: dict, b: dict) -> bool:
    """Two claims conflict if they disagree on the action, the root cause, or
    (for a shift) the source/target campaigns."""
    for k in ("action", "root_cause"):
        if a.get(k) and b.get(k) and a[k] != b[k]:
            return True
    if a.get("action") in ("shift_budget", "increase_budget") and a.get("action") == b.get("action"):
        for k in ("source_campaign", "target_campaign"):
            if a.get(k) and b.get(k) and a[k] != b[k]:
                return True
    return False


def detect_conflict(messages: List[Message]) -> bool:
    if any(m.veto for m in messages):
        return True
    actions = {m.claim.get("action") for m in messages if m.claim.get("action")}
    roots = {m.claim.get("root_cause") for m in messages if m.claim.get("root_cause")}
    return len(actions) > 1 or len(roots) > 1


# ----------------------------------------------------------------- ruling

def _conservative(messages: List[Message]) -> dict:
    """no_action, but keep the best-evidenced root cause the panel identified."""
    ruling = dict(NO_ACTION)
    diagnostic = [m for m in messages if m.claim.get("root_cause")]
    if diagnostic:
        best = max(diagnostic, key=lambda m: (len(m.evidence), m.confidence))
        ruling["root_cause"] = best.claim["root_cause"]
    return ruling


def coordinator_rule(messages: List[Message]):
    """Return (ruling_claim, reason)."""
    vetoes = [m for m in messages if m.veto]
    if vetoes:
        v = max(vetoes, key=lambda m: (len(m.evidence), m.confidence))
        ruling = dict(v.veto_override) if v.veto_override else _conservative(messages)
        return ruling, f"absolute veto by {v.agent}: {v.veto}"

    candidates = [m for m in messages if m.claim.get("action") and m.claim["action"] != "no_action"]
    if not candidates:
        # everyone says hold (or nobody proposed an action) -> hold, best diagnosis
        return _conservative(messages), "consensus: no action warranted"

    ranked = sorted(candidates, key=lambda m: (len(m.evidence), m.confidence), reverse=True)
    top = ranked[0]
    if len(ranked) >= 2:
        second = ranked[1]
        tied = (len(top.evidence), round(top.confidence, 6)) == \
               (len(second.evidence), round(second.confidence, 6))
        if tied and claims_conflict(top.claim, second.claim):
            return _conservative(messages), "tie on evidence+confidence -> conservative default"
    return dict(top.claim), (f"{top.agent} wins on evidence "
                             f"({len(top.evidence)} refs, conf {top.confidence:.2f})")


# ----------------------------------------------------------------- debate loop

def run_debate(initial: List[Message], rebut_fn: Optional[Callable] = None,
               max_rounds: int = 2, rule: Callable = coordinator_rule) -> DebateResult:
    """Round 1 = `initial`. While a conflict persists, run up to `max_rounds`
    rebuttal rounds (each produced by `rebut_fn(messages, round_no)`), then rule."""
    messages = list(initial)
    conflict0 = detect_conflict(messages)
    transcript = [{"round": "round1", "messages": [m.to_dict() for m in messages]}]
    rounds = 0
    while detect_conflict(messages) and rounds < max_rounds:
        rounds += 1
        if rebut_fn is not None:
            messages = list(rebut_fn(messages, rounds))
        transcript.append({"round": f"rebuttal{rounds}",
                           "messages": [m.to_dict() for m in messages]})
        if rebut_fn is None:
            break  # nothing changes without a rebuttal producer; avoid spinning
    ruling, reason = rule(messages)
    transcript.append({"round": "ruling", "ruling": ruling, "reason": reason})
    return DebateResult(ruling=ruling, reason=reason, rounds=rounds,
                        conflict_detected=conflict0, transcript=transcript)


def to_decision(claim: dict, rationale: str = "") -> dict:
    """Fill a claim out to the full harness decision schema."""
    d = {k: None for k in DECISION_FIELDS}
    d.update({k: claim.get(k) for k in DECISION_FIELDS if k in claim})
    if d["root_cause"] is None:
        d["root_cause"] = "noise"
    if d["action"] is None:
        d["action"] = "no_action"
    d["rationale"] = rationale or claim.get("rationale", "")
    return d
