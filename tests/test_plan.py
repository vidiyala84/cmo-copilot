"""Multi-item plan: a reallocation can be several actions, including a new campaign.

Covers the plural policy (`recommend_actions`), the plan-assembly tool
(`recommend_portfolio`), the set-based plan scorer (`harness.score_plan`), and the
end-to-end M1 scenario where the PlannerAgent beats the single-action baseline.
"""
import pytest

from cmo.agents import MockHeuristicAgent, PlannerAgent
from cmo.datagen import generate_base
from cmo.harness import score, score_plan
from cmo.policy import recommend_actions
from cmo.scenarios import MULTI_ITEM_SCENARIO, SCENARIOS
from cmo.tools import ScenarioEnv


def _drivers(ctr=1.0, cvr=1.0, aov=1.0, elasticity=0.8, roas=-10.0, gid="G1"):
    return {"group_id": gid, "roas_change_pct": roas, "drivers": {
        "creative": {"metric": "ctr", "ratio": ctr, "change_pct": (ctr - 1) * 100},
        "targeting": {"metric": "cvr", "ratio": cvr, "change_pct": (cvr - 1) * 100},
        "offer_mix": {"metric": "aov", "ratio": aov, "change_pct": (aov - 1) * 100},
        "budget": {"metric": "elasticity", "ratio": elasticity, "change_pct": None}}}


@pytest.fixture(scope="module")
def base():
    return generate_base()


# --- the plural policy: one group can need several fixes --------------------

def test_two_funnel_stages_moving_yield_two_items():
    recs = recommend_actions(_drivers(ctr=0.75, cvr=0.78))
    actions = {r.action for r in recs}
    assert actions == {"refresh_creative", "fix_targeting"}
    assert all(r.target_group == "G1" for r in recs)


def test_healthy_group_yields_no_items():
    assert recommend_actions(_drivers(ctr=0.99, cvr=1.01)) == []


def test_learning_phase_is_not_a_plan_item():
    # patience is the absence of an action, not one
    assert recommend_actions(_drivers(cvr=0.5), flags={"last_edited_days_ago": 3}) == []


def test_budget_cap_is_a_single_increase_item():
    recs = recommend_actions(_drivers(), flags={"lost_impression_share_budget_pct": 45})
    assert [r.action for r in recs] == ["increase_budget"]


# --- the plan-assembly tool ------------------------------------------------

def test_recommend_portfolio_builds_the_expected_plan(base):
    env = ScenarioEnv(base, MULTI_ITEM_SCENARIO)
    plan = env.recommend_portfolio()
    pairs = {(it.get("group"), it["action"]) for it in plan["items"]}
    assert pairs == {("G1", "refresh_creative"), ("G1", "fix_targeting"),
                     (None, "launch_campaign")}
    # one group legitimately appears twice, and the new campaign has no group
    assert sum(1 for it in plan["items"] if it.get("group") == "G1") == 2
    assert any(it["action"] == "launch_campaign" and it["group"] is None
               for it in plan["items"])


def test_healthy_account_returns_an_empty_plan(base):
    # S10 ("nothing happened") — the plan names only what to change
    s10 = next(s for s in SCENARIOS if s["id"] == "S10")
    env = ScenarioEnv(base, s10)
    assert env.recommend_portfolio()["items"] == []


# --- the set-based scorer --------------------------------------------------

def test_score_plan_rewards_precision_and_recall():
    exp = {"plan": [{"group": "G1", "action": "refresh_creative"},
                    {"group": "G1", "action": "fix_targeting"},
                    {"group": None, "action": "launch_campaign"}]}
    perfect = {"items": [{"group": "G1", "action": "refresh_creative"},
                         {"group": "G1", "action": "fix_targeting"},
                         {"group": None, "action": "launch_campaign"}]}
    assert score_plan(perfect, exp)[0] == 1.0
    # 2 of 3 correct, no spurious -> F1 = 0.8
    two = {"items": exp["plan"][:2]}
    assert score_plan(two, exp)[0] == 0.8
    # a spurious item costs precision
    noisy = {"items": exp["plan"] + [{"group": "G3", "action": "decrease_budget"}]}
    assert score_plan(noisy, exp)[0] < 1.0


def test_single_action_decision_scores_near_zero_on_a_plan():
    exp = {"plan": [{"group": "G1", "action": "refresh_creative"},
                    {"group": "G1", "action": "fix_targeting"},
                    {"group": None, "action": "launch_campaign"}]}
    single = {"action": "shift_budget", "source_campaign": "G1", "target_campaign": "G2"}
    assert score_plan(single, exp)[0] == 0.0


# --- end to end: architecture beats the baseline ---------------------------

def test_planner_solves_the_multi_item_scenario(base):
    env = ScenarioEnv(base, MULTI_ITEM_SCENARIO)
    decision = PlannerAgent().decide(env)
    assert score(decision, MULTI_ITEM_SCENARIO["expected"])[0] == 1.0


def test_single_action_baseline_fails_the_multi_item_scenario(base):
    env = ScenarioEnv(base, MULTI_ITEM_SCENARIO)
    decision = MockHeuristicAgent().decide(env)
    assert score(decision, MULTI_ITEM_SCENARIO["expected"])[0] < 0.5


# --- backward compatibility: single-action scoring is untouched ------------

def test_plan_dispatch_does_not_touch_single_action_scenarios():
    s01 = next(s for s in SCENARIOS if s["id"] == "S01")
    assert "plan" not in s01["expected"]
    correct = {"root_cause": "creative_fatigue", "action": "refresh_creative",
               "source_campaign": None, "target_campaign": None}
    # 0.4 root + 0.4 action + 0.2 sourcing (a non-budget fix that moved no money)
    assert score(correct, s01["expected"])[0] == 1.0
