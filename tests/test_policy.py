"""Deterministic evidence -> action mapping (policy.py).

These pin the *mapping*, not the diagnosis. The mapping must be exact and
reproducible; whether the diagnosis is true is the agent's problem.
"""
import pytest

from cmo.datagen import generate_base
from cmo.policy import recommend_action
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv


def _drivers(ctr=1.0, cvr=1.0, aov=1.0, elasticity=0.8, roas=-10.0):
    return {"roas_change_pct": roas, "drivers": {
        "creative": {"metric": "ctr", "ratio": ctr, "change_pct": (ctr - 1) * 100},
        "targeting": {"metric": "cvr", "ratio": cvr, "change_pct": (cvr - 1) * 100},
        "offer_mix": {"metric": "aov", "ratio": aov, "change_pct": (aov - 1) * 100},
        "budget": {"metric": "elasticity", "ratio": elasticity, "change_pct": None}}}


def test_ctr_drop_is_a_creative_problem_not_a_budget_one():
    r = recommend_action(_drivers(ctr=0.75))
    assert r.action == "refresh_creative"
    assert not r.ambiguous


def test_cvr_drop_is_a_targeting_problem():
    r = recommend_action(_drivers(cvr=0.80))
    assert r.action == "fix_targeting"


def test_small_moves_are_noise_not_a_fix():
    r = recommend_action(_drivers(ctr=0.97, cvr=0.98))
    assert r.action == "no_action"


def test_learning_phase_flag_overrides_the_funnel():
    """Even with a real ctr collapse, an unconverged campaign must be left alone."""
    r = recommend_action(_drivers(ctr=0.6), flags={"last_edited_days_ago": 3})
    assert r.action == "no_action"


def test_budget_cap_flag_recommends_more_budget():
    r = recommend_action(_drivers(), flags={"lost_impression_share_budget_pct": 45})
    assert r.action == "increase_budget"


def test_two_stages_moving_together_is_flagged_ambiguous():
    r = recommend_action(_drivers(ctr=0.75, cvr=0.74))
    assert r.ambiguous
    assert r.alternatives


def test_severe_cvr_collapse_admits_it_might_be_tracking():
    """The tell of a broken pixel: conversions vanish while clicks hold."""
    r = recommend_action(_drivers(ctr=1.0, cvr=0.14))
    assert r.ambiguous
    assert "fix_tracking" in r.alternatives


def test_recommendation_is_deterministic():
    d = _drivers(ctr=0.7)
    assert recommend_action(d).as_dict() == recommend_action(d).as_dict()


def test_policy_cannot_diagnose_only_prescribe():
    """The load-bearing limitation: identical funnels, different truths.

    S02 (tracking outage) and a genuine audience collapse look the same to the
    funnel. If this ever starts passing, the rules have quietly absorbed the
    judgement the agent is supposed to supply.
    """
    base = generate_base()
    env = ScenarioEnv(base, next(s for s in SCENARIOS if s["id"] == "S02"))
    rec = env.recommend_action("G1")
    assert rec["action"] != "fix_tracking"   # rules get it wrong...
    assert rec["ambiguous"] is True          # ...but must say so
