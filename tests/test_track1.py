"""H1-3 — MemoryAgent: signatures, overrides, corrections, and the climbing curve."""
import pytest

from cmo.datagen import generate_base
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv
from tracks.track1.memory_store import MemoryStore
from tracks.track1.retriever import Retriever
from tracks.track1.memory_agent import (MemoryAgent, MemoryAwareHeuristicAgent,
                                  apply_corrections, expected_to_decision,
                                  load_corrections, reluctance, situation_signature)
from tracks.track1.session_runner import run_sessions


def _metrics(sid):
    sc = next(s for s in SCENARIOS if s["id"] == sid)
    return ScenarioEnv(generate_base(), sc).call("get_campaign_metrics", {})


# ------------------------------------------------------------------ signatures

def test_signatures_distinct_across_scenarios():
    """Every scenario must key to its own memory slot, or corrections cross-wire."""
    sigs = {}
    for sc in SCENARIOS:
        env = ScenarioEnv(generate_base(), sc)
        sig, _ = situation_signature(env.call("get_campaign_metrics", {}),
                                     env.call("find_opportunities", {}))
        sigs[sc["id"]] = sig
    assert len(set(sigs.values())) == len(SCENARIOS), sigs


def test_group_metrics_alone_cannot_separate_an_opportunity_from_noise():
    """Why the signature needs the segment axis.

    S11 hides a +75% audience surge inside ~3% of one group's spend, so the group
    rollup reads it as a quiet week — identical to S10. Drop the opportunities
    argument and the two collide, which would hand S11 the "do nothing"
    correction that S10 taught. This documents the blind spot rather than
    pretending it isn't there.
    """
    def sig(sid, with_segments):
        env = ScenarioEnv(generate_base(), next(s for s in SCENARIOS if s["id"] == sid))
        opps = env.call("find_opportunities", {}) if with_segments else None
        return situation_signature(env.call("get_campaign_metrics", {}), opps)[0]

    assert sig("S10", False) == sig("S11", False)   # blind at group level
    assert sig("S10", True) != sig("S11", True)     # separable with segments


def test_signature_stable_across_repeats():
    a, _ = situation_signature(_metrics("S08"))
    b, _ = situation_signature(_metrics("S08"))
    assert a == b


def test_signature_flags_surface():
    s08, _ = situation_signature(_metrics("S08"))
    s09, _ = situation_signature(_metrics("S09"))
    assert "flag_learning_phase_G1" in s08
    assert "flag_budget_cap_G5" in s09


# ------------------------------------------------------------------ helpers

def test_expected_to_decision_no_action():
    d = expected_to_decision({"root_cause": "seasonality", "action": "no_action",
                              "acceptable_targets": [], "acceptable_sources": []})
    assert d["action"] == "no_action" and d["shift_pct"] is None


def test_reluctance_levels():
    assert reluctance("shift_budget", "shift_budget") == 1   # relabel
    assert reluctance("shift_budget", "no_action") == 2      # patience
    assert reluctance("shift_budget", "increase_budget") == 3


# ------------------------------------------------------------------ overrides

def test_preference_fixes_brand_trap_s07():
    store = MemoryStore(db_path=":memory:")
    apply_corrections(store, load_corrections(), after_session=1)
    agent = MemoryAgent(MemoryAwareHeuristicAgent(), store, Retriever(store))
    sc = next(s for s in SCENARIOS if s["id"] == "S07")
    env = ScenarioEnv(generate_base(), sc)
    d = agent.decide(env, session=2)
    assert d["action"] == "no_action"
    assert d["root_cause"] == "brand_demand_dip"


def test_outcome_precedent_changes_course_after_reluctance():
    """A patience trap (S08) needs two backfires before the agent adopts no_action."""
    store = MemoryStore(db_path=":memory:")
    agent = MemoryAgent(MemoryAwareHeuristicAgent(), store, Retriever(store))
    sc = next(s for s in SCENARIOS if s["id"] == "S08")

    def one_session(session):
        env = ScenarioEnv(generate_base(), sc)
        d = agent.decide(env, session)
        from cmo.harness import score
        s, _ = score(d, sc["expected"])
        agent.record_outcome(env, sc, d, s, session)
        return d

    d1 = one_session(1)
    assert d1["action"] == "shift_budget"          # cold: falls in the trap
    d2 = one_session(2)
    assert d2["action"] == "shift_budget"          # 1 backfire < reluctance 2
    d3 = one_session(3)
    assert d3["action"] == "no_action"             # 2 backfires -> patience
    assert d3["root_cause"] == "learning_phase"


# ------------------------------------------------------------------ the curve

def test_curve_climbs_at_least_1_5(mock_baseline_total):
    report = run_sessions(sessions=5, mock=True, db_path=":memory:")
    assert report["session1_total"] == pytest.approx(mock_baseline_total)  # cold == baseline
    assert report["session_last_total"] >= report["session1_total"] + 1.5
    # non-decreasing across sessions
    curve = report["curve"]
    assert all(curve[i + 1] >= curve[i] - 1e-9 for i in range(len(curve) - 1))
    # the baseline never moves
    assert report["baseline_total"] == pytest.approx(mock_baseline_total)


def test_curve_deterministic():
    a = run_sessions(sessions=5, mock=True, db_path=":memory:")["curve"]
    b = run_sessions(sessions=5, mock=True, db_path=":memory:")["curve"]
    assert a == b


def test_context_tokens_bounded():
    """Retrieval keeps injected context bounded even as memories accumulate."""
    report = run_sessions(sessions=5, mock=True, db_path=":memory:")
    for s in report["per_session"]:
        assert s["avg_context_tokens"] <= 1600  # ~1500 cap + a few preference lines


def test_traps_fixed_by_session_5():
    report = run_sessions(sessions=5, mock=True, db_path=":memory:")
    last = {r["scenario"]: r["score"] for r in report["per_session"][-1]["results"]}
    for trap in ("S07", "S08", "S09"):
        assert last[trap] >= 0.8, (trap, last[trap])
