"""The 100-question benchmark: deterministic generation, sound ground truth.

The whole point of a generated benchmark is that it is honest — every question's
correct answer must be provably in the data, and the set must be reproducible.
"""
import pytest

from cmo.agents import MockHeuristicAgent, StructuredAgent
from cmo.benchmark import generate, run, summarize, validate
from cmo.datagen import generate_base


@pytest.fixture(scope="module")
def base():
    return generate_base()


@pytest.fixture(scope="module")
def scenarios():
    return generate()


def test_split_is_40_40_20(scenarios):
    from collections import Counter
    c = Counter(s["difficulty"] for s in scenarios)
    assert len(scenarios) == 100
    assert c == {"simple": 40, "medium": 40, "complex": 20}


def test_generation_is_deterministic():
    a, b = generate(), generate()
    assert [s["id"] for s in a] == [s["id"] for s in b]
    assert [s["expected"] for s in a] == [s["expected"] for s in b]


def test_every_question_is_verified(base, scenarios):
    bad = [s["id"] for s in scenarios if not validate(s, base)]
    assert bad == [], f"unverifiable questions (answer not in data): {bad}"


def test_complex_questions_are_plans_others_are_single(scenarios):
    for s in scenarios:
        if s["difficulty"] == "complex":
            assert "plan" in s["expected"] and len(s["expected"]["plan"]) >= 2
        else:
            assert "plan" not in s["expected"]


def test_complex_has_a_group_with_two_fixes_somewhere(scenarios):
    # the M1 shape — at least one complex plan puts two actions on one group
    def two_on_one(plan):
        from collections import Counter
        c = Counter(it["group"] for it in plan if it["group"])
        return any(v >= 2 for v in c.values())
    assert any(two_on_one(s["expected"]["plan"])
               for s in scenarios if s["difficulty"] == "complex")


def test_structured_agent_aces_complex_plans(base, scenarios):
    complex_scen = [s for s in scenarios if s["difficulty"] == "complex"]
    s = summarize(run(StructuredAgent(), complex_scen, base))
    assert s["by_difficulty"]["complex"]["pct"] == 100.0


def test_naive_baseline_cannot_do_multi_item_plans(base, scenarios):
    complex_scen = [s for s in scenarios if s["difficulty"] == "complex"]
    s = summarize(run(MockHeuristicAgent(), complex_scen, base))
    # a single-move agent can never assemble a multi-item plan
    assert s["by_difficulty"]["complex"]["pct"] == 0.0


def test_structured_beats_naive_overall(base, scenarios):
    naive = summarize(run(MockHeuristicAgent(), scenarios, base))["pct"]
    structured = summarize(run(StructuredAgent(), scenarios, base))["pct"]
    assert structured > naive + 15   # a comfortable, stable margin


def test_gated_planner_wins_all_three_tiers(base, scenarios):
    # the composition (plan behind a trap/risk gate) is the complete solution:
    # it plans the fixes AND holds on the traps — every tier solved.
    from cmo.agents import GatedPlannerAgent
    s = summarize(run(GatedPlannerAgent(), scenarios, base))
    for tier in ("simple", "medium", "complex"):
        assert s["by_difficulty"][tier]["pct"] == 100.0, f"{tier} not solved: {s['by_difficulty']}"
