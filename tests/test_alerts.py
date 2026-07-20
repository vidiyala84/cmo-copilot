"""H3-1 — alerts + triage: trivial dips never reach diagnosis."""
import pytest

from cmo.datagen import generate_base
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv
from tracks.track4.alerts import (all_alerts, make_scenario_alerts, make_trivial_alerts,
                           material_change_pct, triage)


def _metrics(sid):
    sc = next(s for s in SCENARIOS if s["id"] == sid)
    return ScenarioEnv(generate_base(), sc).call("get_campaign_metrics", {})


def test_one_alert_per_scenario():
    alerts = make_scenario_alerts()
    assert len(alerts) == len(SCENARIOS)
    assert {a.scenario_id for a in alerts} == {s["id"] for s in SCENARIOS}


def test_trivial_alerts_always_ignored():
    for a in make_trivial_alerts():
        assert triage(a)["severity"] == "ignore"


def test_trivial_never_investigate_even_scanned_together():
    for a in all_alerts():
        if a.scenario_id is None:  # trivial ones
            assert triage(a)["severity"] == "ignore"


def test_material_change_detects_spike_and_drop():
    assert material_change_pct(_metrics("S06")) >= 12   # a spiking winner
    assert material_change_pct(_metrics("S03")) >= 12   # a broad drop


@pytest.mark.parametrize("sid,expected", [
    ("S01", "investigate"), ("S03", "investigate"), ("S06", "investigate"),
    ("S07", "investigate"), ("S09", "investigate"),
    ("S10", "ignore"),  # genuine noise -> nothing to do
])
def test_scenario_triage(sid, expected):
    alert = next(a for a in make_scenario_alerts() if a.scenario_id == sid)
    assert triage(alert, metrics=_metrics(sid))["severity"] == expected


def test_threshold_override():
    alert = make_trivial_alerts()[0]  # 2% declared
    assert triage(alert, threshold=1.0)["severity"] == "investigate"
    assert triage(alert, threshold=50.0)["severity"] == "ignore"
