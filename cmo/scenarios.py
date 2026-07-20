"""10 scripted scenarios with known right answers.

Each scenario perturbs the last WINDOW days of the base dataset and declares
the expected decision. The harness scores any agent against `expected`.

expected fields:
  root_cause          canonical label
  action              shift_budget | increase_budget | fix_tracking | no_action
  acceptable_targets  list of ok target campaign ids (for shift/increase)
  acceptable_sources  list of ok source ids ([] = any non-forbidden)
  forbidden_sources   sources that make the answer wrong (e.g. brand campaign)
"""
from cmo.config import N_DAYS, WINDOW

START = N_DAYS - WINDOW + 1  # first perturbed day (77)


def _recent(row):
    return row["day"] >= START


def _ramp(row):
    """0..1 linear ramp across the perturbation window."""
    return (row["day"] - START + 1) / WINDOW


# ---- perturbation functions (mutate row dicts in place) ----

def creative_fatigue(rows, meta):
    for r in rows:
        if r["group_id"] == "G1" and _recent(r):
            f = 1 - 0.40 * _ramp(r)          # CTR decays to -40%
            r["clicks"] = round(r["clicks"] * f, 1)
            r["conversions"] = round(r["conversions"] * f, 2)
            r["revenue"] = round(r["revenue"] * f, 2)


def tracking_outage(rows, meta):
    for r in rows:
        if r["group_id"] == "G1" and _recent(r):
            # conversions/revenue collapse overnight; clicks untouched = the tell
            r["conversions"] = round(r["conversions"] * 0.15, 2)
            r["revenue"] = round(r["revenue"] * 0.15, 2)


def seasonality(rows, meta):
    for r in rows:
        if _recent(r):
            r["conversions"] = round(r["conversions"] * 0.75, 2)
            r["revenue"] = round(r["revenue"] * 0.75, 2)


def audience_saturation(rows, meta):
    for r in rows:
        if r["group_id"] == "G3" and _recent(r):
            f = 1 - 0.35 * _ramp(r)          # CVR decays, clicks fine
            r["conversions"] = round(r["conversions"] * f, 2)
            r["revenue"] = round(r["revenue"] * f, 2)
            # the tell: the finite audience shrinks, so frequency climbs — this is
            # saturation, not a targeting error (which leaves frequency flat).
            r["reach"] = int(r["reach"] * (1 - 0.45 * _ramp(r)))


def competitor_pressure(rows, meta):
    for r in rows:
        if r["group_id"] == "G4" and _recent(r):
            # same spend buys ~30% fewer impressions (the auction got pricier) -> CPM
            # up. Clicks/conversions fall WITH impressions, so CTR/CVR are unchanged —
            # the creative is fine, the cost rose. Scale the whole impression funnel.
            k = 0.70
            r["impressions"] = int(r["impressions"] * k)
            r["reach"] = int(r["reach"] * k)
            r["clicks"] = round(r["clicks"] * k, 1)
            r["sessions"] = round(r["sessions"] * k, 1)
            r["bounces"] = round(r["bounces"] * k, 1)
            r["conversions"] = round(r["conversions"] * k, 2)
            r["revenue"] = round(r["revenue"] * k, 2)


def winner_opportunity(rows, meta):
    for r in rows:
        if r["group_id"] == "G5" and _recent(r):
            f = 1 + 0.35 * _ramp(r)
            r["conversions"] = round(r["conversions"] * f, 2)
            r["revenue"] = round(r["revenue"] * f, 2)


def brand_demand_dip(rows, meta):
    for r in rows:
        if r["group_id"] == "G2" and _recent(r):
            r["clicks"] = round(r["clicks"] * 0.65, 1)   # brand searches simply down
            r["conversions"] = round(r["conversions"] * 0.60, 2)
            r["revenue"] = round(r["revenue"] * 0.60, 2)


def learning_phase(rows, meta):
    meta["G1"] = {"last_edited_days_ago": 3}             # recently re-built campaign
    for r in rows:
        if r["group_id"] == "G1" and _recent(r):
            import random
            rng = random.Random(r["day"])                # deterministic noise
            f = rng.gauss(0.85, 0.18)                    # noisy, mildly down
            f = max(0.4, min(1.3, f))
            r["conversions"] = round(r["conversions"] * f, 2)
            r["revenue"] = round(r["revenue"] * f, 2)


def budget_cap(rows, meta):
    meta["G5"] = {"lost_impression_share_budget_pct": 45}
    for r in rows:
        if r["group_id"] == "G5" and _recent(r):
            f = 1 + 0.45 * _ramp(r)                      # efficiency up while capped
            r["conversions"] = round(r["conversions"] * f, 2)
            r["revenue"] = round(r["revenue"] * f, 2)
            r["spend"] = round(r["spend"] * 1.06, 2)     # spending right up to the cap -> pacing ~1.0


EMERGING_SEGMENT = "Interest — Fitness"


def emerging_segment(rows, meta):
    """A small audience starts converting far above its norm.

    The point of this scenario is what it looks like from each altitude. The
    segment is ~2% of G1's spend, so at group level nothing happens — the rollup
    every other tool reads shows a flat, healthy account. The signal only exists
    when you aggregate across campaigns by AUDIENCE instead of by group, which
    is a cut the group hierarchy cannot express.

    The right answer is not to reshuffle budget: it is to launch a campaign
    built for the audience that is already telling you it wants you.
    """
    for r in rows:
        if r["segment"] == EMERGING_SEGMENT and _recent(r):
            f = 1 + 1.4 * _ramp(r)          # conversions climb to ~2.4x
            r["conversions"] = round(r["conversions"] * f, 2)
            r["revenue"] = round(r["revenue"] * f, 2)


def multi_issue(rows, meta):
    """Three things wrong at once — the realistic case a single action can't answer.

    G1 has TWO independent problems stacked: its ad tired (ctr down -> creative)
    AND its clicks convert worse (cvr down -> targeting). One group, two fixes.
    Meanwhile the Fitness audience is quietly converting far above its norm — a
    new-campaign opportunity invisible in the group rollup. The right answer is a
    PLAN: refresh G1's creative, fix G1's targeting, and launch a Fitness campaign
    — not a single budget shift.
    """
    for r in rows:
        if not _recent(r):
            continue
        if r["segment"] == EMERGING_SEGMENT:
            # The surging sub-audience is thriving independently of the group's
            # mainstream ad problems — it is not dragged down by them.
            gf = 1 + 1.4 * _ramp(r)       # emerging audience worth its own campaign
            r["conversions"] = round(r["conversions"] * gf, 2)
            r["revenue"] = round(r["revenue"] * gf, 2)
        elif r["group_id"] == "G1":
            # Both funnel stages move well past the 10% "material" bar even after
            # the surging Fitness sub-audience lifts G1's aggregate conversions.
            cf = 1 - 0.40 * _ramp(r)      # creative: clicks/ctr decay
            tf = 1 - 0.55 * _ramp(r)      # targeting: conversions fall FURTHER than clicks
            r["clicks"] = round(r["clicks"] * cf, 1)
            r["conversions"] = round(r["conversions"] * cf * tf, 2)
            r["revenue"] = round(r["revenue"] * cf * tf, 2)


def landing_page_break(rows, meta):
    """Real visitors still arrive, but the page/checkout is broken.

    Clicks and sessions hold steady, but bounce_rate SPIKES and conversions
    collapse. Looks identical to a tracking outage on the funnel (CVR craters) —
    except a tracking outage leaves bounce flat. The bounce spike is the tell,
    and the fix is the landing page, not the pixel and not the budget.
    """
    for r in rows:
        if r["group_id"] == "G1" and _recent(r):
            headroom = max(0.0, r["sessions"] - r["bounces"])
            r["bounces"] = round(r["bounces"] + headroom * 0.90 * _ramp(r), 1)
            f = 1 - 0.80 * _ramp(r)
            r["conversions"] = round(r["conversions"] * f, 2)
            r["revenue"] = round(r["revenue"] * f, 2)


def funnel_leak(rows, meta):
    """The ads are healthy; the money leaks downstream.

    Clicks, conversions, CTR and CVR all hold — but revenue per conversion
    collapses (refunds, a discount leak, or degraded lead quality). ROAS falls,
    so the instinct is to cut the group. That's wrong: the ads are working, the
    leak is past the click. The right ad-side move is to HOLD and escalate.
    """
    for r in rows:
        if r["group_id"] == "G4" and _recent(r):
            r["revenue"] = round(r["revenue"] * (1 - 0.55 * _ramp(r)), 2)


def over_saturation(rows, meta):
    """We over-invested a group past its efficient frontier.

    Spend was ramped up hard, but conversions barely followed (diminishing
    returns) and frequency climbed — so ROAS fell. Unlike audience_saturation
    (spend flat, audience decays on its own), the tell here is that SPEND ROSE.
    The fix isn't to re-target — it's to pull budget back to the efficient point.
    """
    for r in rows:
        if r["group_id"] == "G1" and _recent(r):
            s = 1 + 0.55 * _ramp(r)                    # we ramped spend +55%
            g = 1 + 0.15 * _ramp(r)                    # conversions grew only +15% (diminishing)
            r["spend"] = round(r["spend"] * s, 2)
            r["budget"] = round(r["budget"] * s, 2)    # budget raised to allow the over-spend
            r["impressions"] = int(r["impressions"] * s)
            r["reach"] = int(r["reach"] * (1 + 0.08 * _ramp(r)))  # audience barely grows -> frequency up
            r["clicks"] = round(r["clicks"] * s, 1)    # ctr flat
            r["sessions"] = round(r["sessions"] * s, 1)
            r["bounces"] = round(r["bounces"] * s, 1)  # bounce_rate flat
            r["conversions"] = round(r["conversions"] * g, 2)
            r["revenue"] = round(r["revenue"] * g, 2)


DEAD_SEGMENT = "Broad"  # a prospecting audience that just never converts


def dead_campaign(rows, meta):
    """A structurally unprofitable segment — not a fixable dip.

    One audience ('Broad', ~across G1's campaigns) has ROAS far below break-even
    and stays there: creative is fine, tracking is fine, it just doesn't convert.
    No refresh or re-target rescues it. The right move is to kill it and reclaim
    the spend. Visible only by aggregating across campaigns by AUDIENCE.
    """
    for r in rows:
        if r["segment"] == DEAD_SEGMENT and _recent(r):
            r["conversions"] = round(r["conversions"] * 0.22, 2)   # collapses and stays down
            r["revenue"] = round(r["revenue"] * 0.22, 2)


def noise(rows, meta):
    pass  # base dataset already has noise; nothing real happened


SCENARIOS = [
    dict(id="S01", name="Creative fatigue on Summer Sale", perturb=creative_fatigue,
         expected=dict(root_cause="creative_fatigue", action="refresh_creative",
                       acceptable_targets=[], acceptable_sources=[],
                       forbidden_sources=["G2"])),
    dict(id="S02", name="Tracking outage disguised as decay", perturb=tracking_outage,
         expected=dict(root_cause="tracking_outage", action="fix_tracking",
                       acceptable_targets=[], acceptable_sources=[], forbidden_sources=[])),
    dict(id="S03", name="Seasonal dip across the board", perturb=seasonality,
         expected=dict(root_cause="seasonality", action="no_action",
                       acceptable_targets=[], acceptable_sources=[], forbidden_sources=[])),
    dict(id="S04", name="Retargeting audience saturated", perturb=audience_saturation,
         expected=dict(root_cause="audience_saturation", action="fix_targeting",
                       acceptable_targets=[], acceptable_sources=[],
                       forbidden_sources=["G2"])),
    dict(id="S05", name="Competitor bidding up Generic Search", perturb=competitor_pressure,
         expected=dict(root_cause="competitor_pressure", action="shift_budget",
                       acceptable_targets=["G5", "G1", "G3"], acceptable_sources=["G4"],
                       forbidden_sources=["G2"])),
    dict(id="S06", name="Advantage+ trending up", perturb=winner_opportunity,
         expected=dict(root_cause="winner_opportunity", action="shift_budget",
                       acceptable_targets=["G5"], acceptable_sources=["G4", "G1"],
                       forbidden_sources=["G2"])),
    dict(id="S07", name="Brand demand dip (floor trap)", perturb=brand_demand_dip,
         expected=dict(root_cause="brand_demand_dip", action="no_action",
                       acceptable_targets=[], acceptable_sources=[],
                       forbidden_sources=["G2"])),
    dict(id="S08", name="Learning phase wobble (patience trap)", perturb=learning_phase,
         expected=dict(root_cause="learning_phase", action="no_action",
                       acceptable_targets=[], acceptable_sources=[],
                       forbidden_sources=["G1"])),
    dict(id="S09", name="Winner capped by budget", perturb=budget_cap,
         expected=dict(root_cause="budget_cap", action="increase_budget",
                       acceptable_targets=["G5"], acceptable_sources=["G4", "G1", "G3"],
                       forbidden_sources=["G2"])),
    dict(id="S10", name="Nothing actually happened", perturb=noise,
         expected=dict(root_cause="noise", action="no_action",
                       acceptable_targets=[], acceptable_sources=[], forbidden_sources=[])),
    dict(id="S11", name="Emerging audience worth a new campaign", perturb=emerging_segment,
         expected=dict(root_cause="emerging_segment", action="launch_campaign",
                       acceptable_targets=[], acceptable_sources=[],
                       forbidden_sources=["G2"])),
    dict(id="S12", name="Landing-page break (looks like tracking)", perturb=landing_page_break,
         expected=dict(root_cause="landing_page_break", action="fix_landing_page",
                       acceptable_targets=[], acceptable_sources=[], forbidden_sources=[])),
    dict(id="S13", name="Downstream funnel leak (ads are fine)", perturb=funnel_leak,
         expected=dict(root_cause="funnel_leak", action="no_action",
                       acceptable_targets=[], acceptable_sources=[],
                       forbidden_sources=["G2", "G4"])),
    dict(id="S14", name="Over-invested past the efficient frontier", perturb=over_saturation,
         expected=dict(root_cause="over_saturation", action="decrease_budget",
                       acceptable_targets=["G1"], acceptable_sources=[],
                       forbidden_sources=["G2"])),
    dict(id="S15", name="Structurally dead audience (kill it)", perturb=dead_campaign,
         expected=dict(root_cause="dead_campaign", action="pause_campaign",
                       acceptable_targets=[], acceptable_sources=[],
                       forbidden_sources=["G2"])),
]


# ---------------------------------------------------------------------------
# Multi-item plan scenario — scored on a different rubric (a SET of actions,
# not one), so it lives outside the single-action SCENARIOS list and runs via
# `multi_item.py`. `expected["plan"]` is what routes the harness to plan scoring.
# ---------------------------------------------------------------------------
MULTI_ITEM_SCENARIO = dict(
    id="M1",
    name="Multiple issues + a new-campaign opportunity",
    perturb=multi_issue,
    expected=dict(
        root_cause="multi",
        action="multi",
        # a plan is a set of (group, action) items; a NEW campaign has no group.
        plan=[
            {"group": "G1", "action": "refresh_creative"},
            {"group": "G1", "action": "fix_targeting"},
            {"group": None, "action": "launch_campaign"},
        ],
        acceptable_targets=[], acceptable_sources=[], forbidden_sources=["G2"],
    ),
)
