"""H2-2 — society: diagnosis edge, veto on traps, beats baseline, transcripts."""
import pytest

from cmo import harness
from cmo.datagen import generate_base
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv
from tracks.track3.society import (SocietyAgent, analyst_diagnose, forecaster_plan,
                            society_ruling)
from tracks.track3.protocol import Message


def _metrics(sid):
    sc = next(s for s in SCENARIOS if s["id"] == sid)
    return ScenarioEnv(generate_base(), sc).call("get_campaign_metrics", {})


# ------------------------------------------------------------------ analyst

@pytest.mark.parametrize("sid,root", [
    ("S01", "creative_fatigue"), ("S02", "tracking_outage"), ("S03", "seasonality"),
    ("S04", "audience_saturation"), ("S05", "competitor_pressure"),
    ("S06", "winner_opportunity"), ("S07", "brand_demand_dip"),
    ("S08", "learning_phase"), ("S09", "budget_cap"), ("S10", "noise"),
])
def test_analyst_diagnoses_every_scenario(sid, root):
    diagnosed, _ = analyst_diagnose(_metrics(sid))
    assert diagnosed == root


def test_analyst_uses_kind_to_split_fatigue_vs_competitor():
    # both look like "CTR down" to the naive baseline; kind disambiguates
    assert analyst_diagnose(_metrics("S01"))[0] == "creative_fatigue"     # prospecting
    assert analyst_diagnose(_metrics("S05"))[0] == "competitor_pressure"  # nonbrand search


# ------------------------------------------------------------------ forecaster

def test_forecaster_never_targets_brand():
    for sid in ("S01", "S04", "S05", "S06", "S09"):
        _, source, target = forecaster_plan(analyst_diagnose(_metrics(sid))[0], _metrics(sid))
        assert target != "G2"


def test_forecaster_increases_capped_winner():
    action, _, target = forecaster_plan("budget_cap", _metrics("S09"))
    assert action == "increase_budget" and target == "G5"


# ------------------------------------------------------------------ veto

def test_risk_vetoes_brand_and_learning_traps():
    agent = SocietyAgent(mock=True)
    for sid in ("S07", "S08"):
        sc = next(s for s in SCENARIOS if s["id"] == sid)
        agent.decide(ScenarioEnv(generate_base(), sc))
        assert agent.last_transcript["ruling_reason"].lower().startswith("risk veto")
        assert agent.last_transcript["final_decision"]["action"] == "no_action"


# ------------------------------------------------------------------ ruling helper

def test_society_ruling_holds_on_seasonality():
    msgs = [Message("Analyst", {"root_cause": "seasonality", "action": "no_action"}, ["m"], 0.9),
            Message("Forecaster", {"root_cause": "seasonality", "action": "shift_budget",
                                   "source_campaign": "G1", "target_campaign": "G3", "shift_pct": 20}, ["f"], 0.7),
            Message("Risk", {"root_cause": "seasonality", "action": "shift_budget",
                             "source_campaign": "G1", "target_campaign": "G3", "shift_pct": 15}, ["p"], 0.8)]
    ruling, _ = society_ruling(msgs)
    assert ruling["action"] == "no_action"


# ------------------------------------------------------------------ acceptance

def test_society_beats_baseline_by_at_least_2(mock_baseline_total):
    from cmo.agents import MockHeuristicAgent
    baseline = sum(r["score"] for r in harness.run(MockHeuristicAgent()))
    society = sum(r["score"] for r in harness.run(SocietyAgent(mock=True)))
    assert society >= baseline + 2.0
    assert baseline == pytest.approx(mock_baseline_total)


def test_traps_scored_high():
    results = {r["scenario"]: r["score"] for r in harness.run(SocietyAgent(mock=True))}
    assert results["S07"] >= 0.8
    assert results["S08"] >= 0.8


def test_every_decision_has_resolved_conflict(tmp_path):
    agent = SocietyAgent(mock=True, transcripts_dir=tmp_path)
    for sc in SCENARIOS:
        agent.decide(ScenarioEnv(generate_base(), sc))
        assert agent.last_transcript["conflicts_resolved"] >= 1
        assert agent.last_transcript["rounds"] <= 2  # debate stays bounded


def test_evidence_traces_to_tools():
    """Audit trail: the society actually calls the tools it cites."""
    sc = next(s for s in SCENARIOS if s["id"] == "S01")
    env = ScenarioEnv(generate_base(), sc)
    SocietyAgent(mock=True).decide(env)
    called = {e["tool"] for e in env.tool_log}
    assert {"get_campaign_metrics", "forecast_roas", "propose_reallocation"} <= called
