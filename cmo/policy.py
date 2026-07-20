"""Deterministic mapping from evidence to action.

Why this is not in the LLM
--------------------------
Given a diagnosis, the right *kind* of fix is not a judgement call — it is a
lookup. CTR collapsed? That is a creative problem, and no amount of budget
reshuffling repairs an ad nobody clicks. CVR collapsed? Targeting. Saturated
with a queue of demand? Budget. Encoding that mapping here makes it auditable,
testable, and impossible for a model to improvise around: the same evidence
always yields the same recommendation, and every recommendation cites the
number that produced it.

Why the LLM is still required
-----------------------------
This module maps *a diagnosis* to an action. It cannot tell you whether the
diagnosis is true. `diagnose_drivers` reports a tracking outage as "targeting,
cvr -86%" — mechanically correct and completely wrong, because a cvr collapse
that severe with clicks intact is a broken pixel, not a bad audience. Deciding
whether the evidence means what it appears to mean is the judgement this
deliberately does not attempt. Rules pick the fix; the agent decides whether the
fix applies.

So `recommend_action` returns a *candidate* with its supporting evidence and an
explicit `ambiguous` flag — never a verdict.
"""
from dataclasses import dataclass, field
from typing import List, Optional

# How far a funnel metric must move before we call it a cause rather than noise.
# Below this, week-to-week wobble would trigger a "fix" for nothing.
MATERIAL_MOVE = 0.10        # 10% on ctr/cvr/aov
SCALE_ELASTICITY = 0.85     # at/above this a group still has real headroom
SATURATED_ELASTICITY = 0.55  # at/below this extra budget is mostly wasted
IMPLAUSIBLE_COLLAPSE = 0.50  # a >50% single-metric collapse smells like measurement


@dataclass
class Recommendation:
    action: str
    reason: str
    evidence: List[str] = field(default_factory=list)
    ambiguous: bool = False
    alternatives: List[str] = field(default_factory=list)
    target_group: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "reason": self.reason,
            "evidence": self.evidence,
            "ambiguous": self.ambiguous,
            "alternatives": self.alternatives,
            "target_group": self.target_group,
            "note": ("AMBIGUOUS — the evidence supports more than one story. Do not act on this "
                     "without checking which. " if self.ambiguous else "") +
                    "This is a candidate derived from evidence, not a verdict: it assumes the "
                    "diagnosis is true. Verify before acting.",
        }


def recommend_action(drivers: dict, flags: dict = None) -> Recommendation:
    """Map a `diagnose_drivers` result to the fix its evidence implies.

    `flags` carries scenario metadata the funnel cannot see (learning phase,
    budget caps) — the things that make "do nothing" correct despite a move.
    """
    flags = flags or {}
    d = drivers.get("drivers", {})
    roas_change = drivers.get("roas_change_pct")

    def moved(key):
        r = d.get(key, {}).get("ratio")
        return (1.0 - r) if r is not None else 0.0

    ctr_drop, cvr_drop, aov_drop = moved("creative"), moved("targeting"), moved("offer_mix")
    elasticity = d.get("budget", {}).get("ratio", 1.0)

    # --- things that override the funnel entirely ---------------------------
    if flags.get("last_edited_days_ago") is not None:
        return Recommendation(
            action="no_action",
            reason="inside the learning phase — the algorithm has not converged yet",
            evidence=[f"last_edited_days_ago={flags['last_edited_days_ago']}"],
        )

    if flags.get("lost_impression_share_budget_pct"):
        return Recommendation(
            action="increase_budget",
            reason="demand is queued behind a budget cap, not a performance problem",
            evidence=[f"lost_impression_share_budget={flags['lost_impression_share_budget_pct']}%",
                      f"elasticity={elasticity}"],
        )

    # --- the funnel ---------------------------------------------------------
    if cvr_drop >= IMPLAUSIBLE_COLLAPSE and ctr_drop < MATERIAL_MOVE:
        # Mechanically this is "targeting". Physically, an audience does not stop
        # converting by half overnight while still clicking exactly as before.
        return Recommendation(
            action="fix_targeting",
            reason="conversion rate collapsed while clicks held",
            evidence=[f"cvr {d['targeting']['change_pct']}%", f"ctr {d['creative']['change_pct']}%"],
            ambiguous=True,
            alternatives=["fix_tracking"],
        )

    candidates = []
    if ctr_drop >= MATERIAL_MOVE:
        candidates.append(("refresh_creative", "ctr", ctr_drop,
                           "the ad stopped earning attention — new creative, not new budget"))
    if cvr_drop >= MATERIAL_MOVE:
        candidates.append(("fix_targeting", "cvr", cvr_drop,
                           "clicks still come but convert worse — the audience is wrong or exhausted"))
    if aov_drop >= MATERIAL_MOVE:
        candidates.append(("launch_campaign", "aov", aov_drop,
                           "buyers got cheaper — the product/offer mix shifted"))

    if candidates:
        candidates.sort(key=lambda c: -c[2])
        action, metric, drop, reason = candidates[0]
        rec = Recommendation(
            action=action,
            reason=reason,
            evidence=[f"{m}: {d[k]['change_pct']}%" for k, m in
                      (("creative", "ctr"), ("targeting", "cvr"), ("offer_mix", "aov"))],
        )
        # Two funnel stages moving together means the cause is upstream of both.
        if len(candidates) > 1 and candidates[1][2] >= drop * 0.6:
            rec.ambiguous = True
            rec.alternatives = [c[0] for c in candidates[1:]]
        return rec

    # --- nothing in the funnel moved ---------------------------------------
    if elasticity <= SATURATED_ELASTICITY:
        return Recommendation(
            action="decrease_budget",
            reason="no funnel problem, but the group is at its ceiling — the last dollars are wasted",
            evidence=[f"elasticity={elasticity}"],
            ambiguous=True,
            alternatives=["no_action"],
        )
    if elasticity >= SCALE_ELASTICITY and (roas_change or 0) > 0:
        return Recommendation(
            action="increase_budget",
            reason="improving and still scaling — this group has headroom",
            evidence=[f"elasticity={elasticity}", f"roas {roas_change}%"],
        )

    return Recommendation(
        action="no_action",
        reason="no funnel driver moved materially — this is noise, seasonality, or measurement",
        evidence=[f"ctr {d.get('creative', {}).get('change_pct')}%",
                  f"cvr {d.get('targeting', {}).get('change_pct')}%",
                  f"roas {roas_change}%"],
        ambiguous=True,
        alternatives=["fix_tracking", "no_action"],
    )


def recommend_actions(drivers: dict, flags: dict = None) -> List[Recommendation]:
    """Every *actionable* fix a group's evidence implies — a group can need more
    than one, and often nothing.

    `recommend_action` (singular) always answers "what is THE single best fix?" —
    it is the right shape for the one-decision harness. This is its plan-oriented
    sibling: a group whose ctr AND cvr both collapsed has two distinct problems (a
    tired ad *and* a wrong audience) and earns two items — a creative refresh and
    a targeting fix. A group with no problem earns none.

    Deliberately conservative about budget: it emits an item only for a real,
    evidenced signal — a moved funnel stage, or a budget-cap flag. It never
    volunteers "cut this saturated group" the way the singular verdict may, so a
    portfolio plan stays precise (and never proposes trimming the floor-protected
    brand group on a hunch). Learning-phase groups get no item: the fix is
    patience, which is the absence of an action, not one.
    """
    flags = flags or {}
    if flags.get("last_edited_days_ago") is not None:
        return []  # learning phase — patience is not a plan item
    if flags.get("lost_impression_share_budget_pct"):
        return [recommend_action(drivers, flags)]  # a real, whole-group signal

    d = drivers.get("drivers", {})
    gid = drivers.get("group_id")

    def moved(key):
        r = d.get(key, {}).get("ratio")
        return (1.0 - r) if r is not None else 0.0

    recs: List[Recommendation] = []
    if moved("creative") >= MATERIAL_MOVE:
        recs.append(Recommendation(
            action="refresh_creative",
            reason="the ad stopped earning attention — new creative, not new budget",
            evidence=[f"ctr {d['creative']['change_pct']}%"], target_group=gid))
    if moved("targeting") >= MATERIAL_MOVE:
        recs.append(Recommendation(
            action="fix_targeting",
            reason="clicks still come but convert worse — the audience is wrong or exhausted",
            evidence=[f"cvr {d['targeting']['change_pct']}%"], target_group=gid))
    return recs
