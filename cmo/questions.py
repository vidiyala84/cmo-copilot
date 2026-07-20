"""5 distinct CMO questions over the same account dynamics.

The point: the same perturbation has a DIFFERENT correct answer depending on what
the CMO is actually asking. A winning campaign is a shift *target* (Q1), a
scale-up *pick* (Q2), and something you must *not cut* (Q5). Averaging across all
five questions gives a benchmark that isn't overfit to one framing.

Each scenario reuses a validated perturbation from scenarios.py; only the
question prompt and the expected answer change per question.
"""
from cmo.portfolio import account_brief
from cmo.scenarios import (creative_fatigue, tracking_outage, seasonality,
                       audience_saturation, competitor_pressure, winner_opportunity,
                       brand_demand_dip, learning_phase, budget_cap, noise)


def _sc(id, name, perturb, root, action, targets=(), sources=(), forbidden=()):
    return {"id": id, "name": name, "perturb": perturb,
            "expected": {"root_cause": root, "action": action,
                         "acceptable_targets": list(targets),
                         "acceptable_sources": list(sources),
                         "forbidden_sources": list(forbidden)}}


QUESTIONS = [
    {
        "id": "Q1", "title": "Reallocation",
        "prompt": (f"Campaign performance dropped this week across {account_brief()}. "
                   "Diagnose the root cause and decide where the budget should go: "
                   "reallocate budget, increase a budget, fix tracking, or do nothing."),
        "scenarios": [
            _sc("Q1a", "Creative fatigue on Summer Sale", creative_fatigue, "creative_fatigue", "shift_budget", ["G5", "G3"], ["G1"], ["G2"]),
            _sc("Q1b", "Retargeting saturated", audience_saturation, "audience_saturation", "shift_budget", ["G5", "G1"], ["G3"], ["G2"]),
            _sc("Q1c", "Brand demand dip (trap)", brand_demand_dip, "brand_demand_dip", "no_action", [], [], ["G2"]),
            _sc("Q1d", "Tracking outage (trap)", tracking_outage, "tracking_outage", "fix_tracking", [], [], []),
            _sc("Q1e", "Seasonal dip", seasonality, "seasonality", "no_action", [], [], []),
        ],
    },
    {
        "id": "Q2", "title": "Scale-up",
        "prompt": ("You have $200,000 of EXTRA budget to invest this month. Decide which single campaign "
                   "group should get the increase — or hold if none is a good bet right now. "
                   "Answer with increase_budget on the right group, or no_action."),
        "scenarios": [
            _sc("Q2a", "Advantage+ trending up", winner_opportunity, "winner_opportunity", "increase_budget", ["G5"], [], ["G2"]),
            _sc("Q2b", "Winner capped by budget", budget_cap, "budget_cap", "increase_budget", ["G5"], [], ["G2"]),
            _sc("Q2c", "Retargeting saturated — don't scale", audience_saturation, "audience_saturation", "no_action", [], [], []),
            _sc("Q2d", "Learning phase — don't scale (trap)", learning_phase, "learning_phase", "no_action", [], [], ["G1"]),
            _sc("Q2e", "Nothing worth scaling", noise, "noise", "no_action", [], [], []),
        ],
    },
    {
        "id": "Q3", "title": "Efficiency audit",
        "prompt": ("Audit efficiency: which campaign groups are underperforming versus their channel benchmark, "
                   "and what should you do about the worst one? Move budget off a genuine underperformer, "
                   "increase a clear winner, or hold."),
        "scenarios": [
            _sc("Q3a", "Competitor bidding up nonbrand", competitor_pressure, "competitor_pressure", "shift_budget", ["G5", "G1", "G3"], ["G4"], ["G2"]),
            _sc("Q3b", "Creative fatigue dragging efficiency", creative_fatigue, "creative_fatigue", "shift_budget", ["G5", "G3"], ["G1"], ["G2"]),
            _sc("Q3c", "Brand dipped but still efficient (trap)", brand_demand_dip, "brand_demand_dip", "no_action", [], [], ["G2"]),
            _sc("Q3d", "Winner beating benchmark", winner_opportunity, "winner_opportunity", "increase_budget", ["G5"], [], ["G2"]),
            _sc("Q3e", "All within benchmark", noise, "noise", "no_action", [], [], []),
        ],
    },
    {
        "id": "Q4", "title": "Health check",
        "prompt": ("Is anything actually BROKEN in measurement, or is this just normal fluctuation? "
                   "Only fix what is genuinely broken (fix_tracking); otherwise do nothing. "
                   "Do not move budget."),
        "scenarios": [
            _sc("Q4a", "Tracking outage", tracking_outage, "tracking_outage", "fix_tracking", [], [], []),
            _sc("Q4b", "Just noise", noise, "noise", "no_action", [], [], []),
            _sc("Q4c", "Seasonal, not broken", seasonality, "seasonality", "no_action", [], [], []),
            _sc("Q4d", "Competitor pressure — real, not broken", competitor_pressure, "competitor_pressure", "no_action", [], [], []),
            _sc("Q4e", "Learning phase — not broken", learning_phase, "learning_phase", "no_action", [], [], []),
        ],
    },
    {
        "id": "Q5", "title": "Patience test",
        "prompt": ("Should you act NOW or WAIT? Only act if intervention clearly helps this week; "
                   "otherwise hold. Answer with a budget move only when it's genuinely warranted, "
                   "else no_action."),
        "scenarios": [
            _sc("Q5a", "Learning phase — wait (trap)", learning_phase, "learning_phase", "no_action", [], [], ["G1"]),
            _sc("Q5b", "Seasonal — wait", seasonality, "seasonality", "no_action", [], [], []),
            _sc("Q5c", "Brand demand dip — wait (trap)", brand_demand_dip, "brand_demand_dip", "no_action", [], [], ["G2"]),
            _sc("Q5d", "Creative fatigue — act", creative_fatigue, "creative_fatigue", "shift_budget", ["G5", "G3"], ["G1"], ["G2"]),
            _sc("Q5e", "Clear winner — act", winner_opportunity, "winner_opportunity", "shift_budget", ["G5"], ["G4", "G1"], ["G2"]),
        ],
    },
]
