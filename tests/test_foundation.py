"""H0-1 — regression tests for the shared foundation (datagen/scenarios/tools/harness)."""
import copy

import pytest

from cmo.config import CONSTRAINTS, N_DAYS, WINDOW
from cmo.datagen import generate_base
from cmo.portfolio import CAMPAIGNS, GROUP_IDS
from cmo.scenarios import SCENARIOS, START
from cmo.tools import ScenarioEnv
from cmo import harness

RECENT_START = N_DAYS - WINDOW + 1


def _scenario(sid):
    return next(s for s in SCENARIOS if s["id"] == sid)


# ---------------------------------------------------------------- datagen

def test_datagen_deterministic_same_seed():
    a = generate_base(seed=42)
    b = generate_base(seed=42)
    assert a == b
    assert len(a) == N_DAYS * len(CAMPAIGNS)  # one row per campaign per day


def test_datagen_differs_across_seeds():
    a = generate_base(seed=42)
    b = generate_base(seed=7)
    assert a != b


def test_datagen_row_shape():
    rows = generate_base()
    r = rows[0]
    assert set(r) == {"day", "campaign_id", "group_id", "segment", "name", "platform", "kind",
                      "spend", "impressions", "clicks", "conversions", "revenue",
                      "reach", "sessions", "bounces", "budget"}


def test_every_row_belongs_to_a_known_group():
    """group_id is what the tool layer rolls up on — an orphan row would vanish."""
    rows = generate_base()
    assert {r["group_id"] for r in rows} == set(GROUP_IDS)


# ---------------------------------------------------------------- scenarios

def test_s02_tracking_outage_clicks_intact_conversions_collapse():
    """The tell of a tracking outage: clicks hold, conversions crater."""
    base = generate_base()
    sc = _scenario("S02")
    perturbed = copy.deepcopy(base)
    meta = {}
    sc["perturb"](perturbed, meta)

    def sel(rows):
        return [r for r in rows if r["group_id"] == "G1" and r["day"] >= START]

    base_c1 = sel(base)
    pert_c1 = sel(perturbed)
    base_clicks = sum(r["clicks"] for r in base_c1)
    pert_clicks = sum(r["clicks"] for r in pert_c1)
    base_conv = sum(r["conversions"] for r in base_c1)
    pert_conv = sum(r["conversions"] for r in pert_c1)

    assert pert_clicks == pytest.approx(base_clicks)          # clicks untouched
    assert pert_conv < base_conv * 0.25                        # conversions collapsed (~15%)


def test_perturbation_only_touches_recent_window():
    """Prior-period rows must be identical to base for a single-campaign scenario."""
    base = generate_base()
    sc = _scenario("S01")  # creative fatigue on C1 only
    perturbed = copy.deepcopy(base)
    sc["perturb"](perturbed, {})
    for b, p in zip(base, perturbed):
        if b["day"] < START:
            assert b == p


def test_s08_sets_learning_phase_flag():
    base = generate_base()
    sc = _scenario("S08")
    meta = {}
    sc["perturb"](copy.deepcopy(base), meta)
    assert meta.get("G1", {}).get("last_edited_days_ago") == 3


# ---------------------------------------------------------------- constraints

def test_constraint_max_shift_cap():
    env = ScenarioEnv(generate_base(), _scenario("S01"))
    over = env.propose_reallocation("G1", "G5", 25)
    assert not over["valid"]
    assert any("exceeds max weekly shift" in v for v in over["violations"])
    ok = env.propose_reallocation("G1", "G5", 15)
    assert ok["valid"]


def test_constraint_brand_floor():
    env = ScenarioEnv(generate_base(), _scenario("S07"))
    res = env.propose_reallocation("G2", "G5", 20)
    assert not res["valid"]
    assert any("floor" in v for v in res["violations"])


def test_constraint_learning_phase():
    env = ScenarioEnv(generate_base(), _scenario("S08"))  # sets C1 last_edited 3d ago
    res = env.propose_reallocation("G1", "G5", 10)
    assert not res["valid"]
    assert any("learning phase" in v for v in res["violations"])


def test_forecast_traces_to_metrics():
    env = ScenarioEnv(generate_base(), _scenario("S01"))
    f = env.forecast_roas("G1", "G5", 15)
    assert "expected_daily_revenue_delta" in f
    assert "moved_daily_usd" in f


def test_tool_log_records_calls():
    env = ScenarioEnv(generate_base(), _scenario("S01"))
    env.call("get_campaign_metrics", {})
    env.call("forecast_roas", {"source_campaign": "G1", "target_campaign": "G5", "shift_pct": 15})
    assert [e["tool"] for e in env.tool_log] == ["get_campaign_metrics", "forecast_roas"]


# ---------------------------------------------------------------- harness scoring

def test_score_perfect_no_action():
    expected = _scenario("S03")["expected"]
    decision = {"root_cause": "seasonality", "action": "no_action",
                "source_campaign": None, "target_campaign": None, "shift_pct": None}
    s, notes = harness.score(decision, expected)
    assert s == 1.0
    assert notes == []


def test_score_forbidden_source_penalised():
    """Moving budget out of the protected brand campaign must lose sourcing credit."""
    expected = _scenario("S07")["expected"]  # brand dip, forbidden source C2
    decision = {"root_cause": "brand_demand_dip", "action": "shift_budget",
                "source_campaign": "G2", "target_campaign": "G5", "shift_pct": 15}
    s, notes = harness.score(decision, expected)
    assert s < 0.5  # wrong action + moved out of protected campaign
    assert any("protected" in n for n in notes)


def test_score_action_and_root_partial_credit():
    """S01's fix is new creative, not a budget move — and needs no source/target."""
    expected = _scenario("S01")["expected"]
    decision = {"root_cause": "creative_fatigue", "action": "refresh_creative",
                "source_campaign": None, "target_campaign": None, "shift_pct": None}
    s, _ = harness.score(decision, expected)
    assert s == 1.0


def test_budget_move_does_not_fix_creative_fatigue():
    """The old answer to S01. Right diagnosis, wrong remedy — must not score full."""
    expected = _scenario("S01")["expected"]
    decision = {"root_cause": "creative_fatigue", "action": "shift_budget",
                "source_campaign": "G1", "target_campaign": "G5", "shift_pct": 15}
    s, notes = harness.score(decision, expected)
    assert s == pytest.approx(0.4)  # root cause only
    assert any("action" in n for n in notes)


def test_crashing_agent_scores_zero():
    class Boom:
        name = "boom"

        def decide(self, env):
            raise RuntimeError("kaboom")

    results = harness.run(Boom())
    assert len(results) == len(SCENARIOS)
    assert all(r["score"] == 0.0 for r in results)


def test_mock_baseline_canary(mock_baseline_total):
    """The whole build's canary: the mock heuristic's score is exact and pinned.

    See MOCK_BASELINE_TOTAL in conftest.py before changing it."""
    from cmo.agents import MockHeuristicAgent
    results = harness.run(MockHeuristicAgent())
    total = sum(r["score"] for r in results)
    assert round(total, 1) == mock_baseline_total
