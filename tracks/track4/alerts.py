"""H3-1 — alert fixtures + triage (Track 4).

Alerts are ambiguous by design: "performance down", no diagnosis attached. One
per scenario, plus three trivial dips that MUST be filtered out at triage —
restraint is production-readiness; the autopilot does not act on noise.

Triage is deliberately cheap (a threshold on the biggest material move, up or
down). `ignore` -> the pipeline logs and exits before spending any diagnosis
budget. `investigate` -> continue to diagnosis.
"""
import os
from dataclasses import dataclass, field
from typing import Optional

from cmo.scenarios import SCENARIOS

TRIAGE_THRESHOLD = float(os.environ.get("TRIAGE_THRESHOLD", "12.0"))  # % material move


@dataclass
class Alert:
    id: str
    text: str
    scenario_id: Optional[str] = None
    declared_drop_pct: float = 0.0        # used when no live metrics are available
    source: str = "roas_monitor"
    meta: dict = field(default_factory=dict)

    def to_dict(self):
        return {"id": self.id, "text": self.text, "scenario_id": self.scenario_id,
                "declared_drop_pct": self.declared_drop_pct, "source": self.source}


def make_scenario_alerts():
    """One ambiguous alert per scenario — same vague text, different underlying truth."""
    return [Alert(id=f"ALERT-{sc['id']}",
                  text="Account performance is down this week — ROAS looks off. Please look into it.",
                  scenario_id=sc["id"], declared_drop_pct=30.0)
            for sc in SCENARIOS]


def make_trivial_alerts():
    """Three tiny dips that triage must reject before diagnosis."""
    return [
        Alert(id="ALERT-TRIV-1", text="ROAS down slightly today.", declared_drop_pct=2.0),
        Alert(id="ALERT-TRIV-2", text="Small dip in conversions this morning.", declared_drop_pct=3.5),
        Alert(id="ALERT-TRIV-3", text="Spend up a hair, ROAS a touch lower.", declared_drop_pct=1.0),
    ]


def all_alerts():
    return make_scenario_alerts() + make_trivial_alerts()


def material_change_pct(metrics: dict) -> float:
    """Magnitude of the biggest ROAS move in either direction (a drop OR a spike
    both warrant a look — a spiking winner is an opportunity)."""
    changes = [(d.get("roas_change_pct") or 0.0) for d in metrics.values()]
    if not changes:
        return 0.0
    return max(max(changes), -min(changes), 0.0)


def triage(alert: Alert, metrics: Optional[dict] = None, threshold: float = TRIAGE_THRESHOLD) -> dict:
    """Classify severity. With live metrics, decide on the real material move;
    otherwise fall back to the alert's declared drop."""
    if metrics is not None:
        mag = material_change_pct(metrics)
        why = f"material move {mag:.1f}%"
    else:
        mag = alert.declared_drop_pct
        why = f"declared drop {mag:.1f}%"
    severity = "investigate" if mag >= threshold else "ignore"
    return {"severity": severity, "magnitude": round(mag, 1),
            "reason": f"{why} vs {threshold:.0f}% threshold -> {severity}"}
