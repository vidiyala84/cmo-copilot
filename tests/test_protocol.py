"""H2-1 — protocol: conflict detection, veto, 2-round bound, ruling policy."""
import pytest

from tracks.track3.protocol import (Message, claims_conflict, coordinator_rule,
                             detect_conflict, run_debate, to_decision)


def _m(agent, action, root=None, evidence=(), conf=0.5, **kw):
    claim = {"action": action}
    if root:
        claim["root_cause"] = root
    claim.update({k: kw[k] for k in ("source_campaign", "target_campaign", "shift_pct") if k in kw})
    return Message(agent=agent, claim=claim, evidence=list(evidence), confidence=conf)


# ------------------------------------------------------------------ conflict

def test_no_conflict_when_agreed():
    msgs = [_m("Analyst", "no_action", "seasonality"), _m("Forecaster", "no_action", "seasonality")]
    assert not detect_conflict(msgs)


def test_conflict_on_action_disagreement():
    msgs = [_m("Analyst", "shift_budget", "creative_fatigue"), _m("Risk", "no_action", "creative_fatigue")]
    assert detect_conflict(msgs)


def test_conflict_on_root_cause():
    msgs = [_m("Analyst", "shift_budget", "creative_fatigue"),
            _m("Forecaster", "shift_budget", "audience_saturation")]
    assert detect_conflict(msgs)


def test_veto_is_conflict():
    m = _m("Risk", "no_action", "brand_demand_dip")
    m.veto = "brand floor breach"
    assert detect_conflict([m])


def test_claims_conflict_source_target():
    a = {"action": "shift_budget", "source_campaign": "G1", "target_campaign": "G5"}
    b = {"action": "shift_budget", "source_campaign": "G1", "target_campaign": "G3"}
    assert claims_conflict(a, b)


# ------------------------------------------------------------------ veto

def test_absolute_veto_wins_over_evidence():
    strong = _m("Forecaster", "shift_budget", "creative_fatigue",
                evidence=["a", "b", "c", "d"], conf=0.99)
    veto = Message(agent="Risk", claim={"action": "no_action"}, evidence=["propose_reallocation:C2"],
                   confidence=0.9, veto="would break the $2k brand floor",
                   veto_override={"root_cause": "brand_demand_dip", "action": "no_action",
                                  "source_campaign": None, "target_campaign": None, "shift_pct": None})
    ruling, reason = coordinator_rule([strong, veto])
    assert ruling["action"] == "no_action"
    assert ruling["root_cause"] == "brand_demand_dip"
    assert "veto" in reason.lower()


# ------------------------------------------------------------------ ruling policy (table-driven)

@pytest.mark.parametrize("msgs,expected_action,note", [
    # more evidence wins
    ([_m("A", "shift_budget", "creative_fatigue", evidence=["x", "y"], conf=0.6),
      _m("B", "increase_budget", "budget_cap", evidence=["x"], conf=0.9)],
     "shift_budget", "evidence count beats confidence"),
    # tie on evidence -> confidence breaks it
    ([_m("A", "shift_budget", "creative_fatigue", evidence=["x"], conf=0.6),
      _m("B", "increase_budget", "budget_cap", evidence=["y"], conf=0.9)],
     "increase_budget", "equal evidence -> higher confidence"),
    # full tie + conflict -> conservative no_action
    ([_m("A", "shift_budget", "creative_fatigue", evidence=["x"], conf=0.7),
      _m("B", "increase_budget", "budget_cap", evidence=["y"], conf=0.7)],
     "no_action", "dead tie -> conservative"),
    # consensus hold
    ([_m("A", "no_action", "seasonality", evidence=["x"]),
      _m("B", "no_action", "seasonality", evidence=["y"])],
     "no_action", "everyone holds"),
])
def test_ruling_policy_table(msgs, expected_action, note):
    ruling, _ = coordinator_rule(msgs)
    assert ruling["action"] == expected_action, note


# ------------------------------------------------------------------ debate bound

def test_debate_bounded_to_two_rounds():
    """Even with a rebuttal producer that never resolves the conflict, rounds <= 2."""
    a = _m("A", "shift_budget", "creative_fatigue", evidence=["x"], conf=0.7)
    b = _m("B", "increase_budget", "budget_cap", evidence=["y"], conf=0.7)

    def never_agree(messages, rnd):
        return messages  # persistent disagreement

    res = run_debate([a, b], rebut_fn=never_agree, max_rounds=2)
    assert res.rounds == 2
    assert res.conflict_detected
    assert res.ruling["action"] == "no_action"  # unresolved -> conservative


def test_debate_resolves_early_when_conflict_clears():
    a = _m("A", "shift_budget", "creative_fatigue", evidence=["x"], conf=0.7)
    b = _m("B", "shift_budget", "audience_saturation", evidence=["y"], conf=0.7)

    def concede(messages, rnd):
        # B concedes to A's root cause in round 1
        return [messages[0], _m("B", "shift_budget", "creative_fatigue", evidence=["y", "z"], conf=0.8)]

    res = run_debate([a, b], rebut_fn=concede, max_rounds=2)
    assert res.rounds == 1
    assert res.ruling["action"] == "shift_budget"


def test_to_decision_fills_schema():
    d = to_decision({"action": "shift_budget", "root_cause": "creative_fatigue"})
    assert set(d) >= {"root_cause", "action", "source_campaign", "target_campaign", "shift_pct", "rationale"}
    assert d["source_campaign"] is None
