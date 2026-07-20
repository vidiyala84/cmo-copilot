"""The shared tool belt. Identical for every architecture (T1/T3/T4 and baseline).

ScenarioEnv wraps one perturbed dataset + portfolio metadata + constraints and
exposes the tools. `OPENAI_TOOL_SPECS` is the function-calling schema for Qwen's
OpenAI-compatible API.

Two design rules, both load-bearing at 300 campaigns:

1. **Roll up by default, drill down on request.** `get_campaign_metrics` answers
   at GROUP level — 5 rows, ~500 tokens — no matter how many campaigns sit
   underneath. Returning all 300 would cost ~32k tokens of context and break a
   32k window outright (`runs/scaling.json`). `get_group_campaigns` is the
   escape hatch, and it is *bounded*: it returns at most `limit` campaigns, so
   an agent can gather evidence without ever paying O(N).

2. **Index once, aggregate many.** The dataset is 27k rows. Filtering the full
   list per aggregation would be O(rows x groups) on every tool call, so rows
   are bucketed by group and by campaign at construction and every aggregation
   walks only its own bucket.
"""
import copy
import json
import time
from collections import defaultdict

from cmo.config import CONSTRAINTS, N_DAYS, RUNS_DIR, WINDOW
from cmo.modeling import calibrate_to_group, fit_response_curve, interpret_elasticity
from cmo.policy import recommend_action, recommend_actions
from cmo.portfolio import BY_GROUP, BY_SEGMENT, GROUP_IDS, GROUP_META

RECENT_START = N_DAYS - WINDOW + 1

MAX_DRILLDOWN = 25  # hard cap on drill-down rows — the O(1)-context guarantee

BENCHMARKS = {  # synthetic "industry KB" — every number carries a source tag
    "meta_prospecting_roas": {"value": 3.0, "source": "synthetic-kb-2026-06"},
    "meta_retargeting_roas": {"value": 4.2, "source": "synthetic-kb-2026-06"},
    "google_brand_roas": {"value": 5.5, "source": "synthetic-kb-2026-06"},
    "google_nonbrand_roas": {"value": 2.2, "source": "synthetic-kb-2026-06"},
}

_SUM_FIELDS = ("spend", "impressions", "clicks", "conversions", "revenue",
               "reach", "sessions", "bounces", "budget")


def _agg(rows, d0, d1):
    """Aggregate an already-bucketed row list over the day window [d0, d1].

    Derives the funnel KPIs (roas/ctr/cvr) plus the richer signals that let the
    agents tell look-alike problems apart: cpm/cpc/cpa (auction cost), frequency
    (audience saturation), bounce_rate (landing-page health), and pacing
    (spend vs the budget cap)."""
    sel = [r for r in rows if d0 <= r["day"] <= d1]
    s = {k: sum(r.get(k, 0) for r in sel) for k in _SUM_FIELDS}
    days = max(1, len({r["day"] for r in sel}))
    s["roas"] = round(s["revenue"] / s["spend"], 3) if s["spend"] else 0.0
    s["ctr"] = round(s["clicks"] / s["impressions"], 5) if s["impressions"] else 0.0
    s["cvr"] = round(s["conversions"] / s["clicks"], 5) if s["clicks"] else 0.0
    s["cpm"] = round(1000 * s["spend"] / s["impressions"], 2) if s["impressions"] else 0.0
    s["cpc"] = round(s["spend"] / s["clicks"], 2) if s["clicks"] else 0.0
    s["cpa"] = round(s["spend"] / s["conversions"], 2) if s["conversions"] else 0.0
    s["frequency"] = round(s["impressions"] / s["reach"], 2) if s["reach"] else 0.0
    s["bounce_rate"] = round(s["bounces"] / s["sessions"], 4) if s["sessions"] else 0.0
    s["pacing"] = round(s["spend"] / s["budget"], 3) if s["budget"] else 0.0
    s["daily_spend"] = round(s["spend"] / days, 2)
    return {k: round(v, 3) if isinstance(v, float) else v for k, v in s.items()}


def _change_pct(prior, recent):
    return round(100 * (recent["roas"] / prior["roas"] - 1), 1) if prior["roas"] else None


class ScenarioEnv:
    def __init__(self, base_rows, scenario):
        # Rows are flat dicts of scalars, so a per-row dict() copy isolates this
        # env's mutations completely — and is ~20x faster than deepcopy, which
        # matters at 27k rows x every scenario in the harness.
        self.rows = [dict(r) for r in base_rows]
        self.meta = {}
        scenario["perturb"](self.rows, self.meta)
        self.scenario_id = scenario["id"]
        self.tool_log = []   # audit trail: every call, args, result digest
        self._curves = {}    # group_id -> fitted ResponseCurve (lazy, per env)

        # Bucket once — see rule 2 in the module docstring.
        self._by_group = defaultdict(list)
        self._by_campaign = defaultdict(list)
        for r in self.rows:
            self._by_group[r["group_id"]].append(r)
            self._by_campaign[r["campaign_id"]].append(r)

    # ---- tools ----
    def get_campaign_metrics(self, group_id=None):
        """Prior vs recent metrics per campaign GROUP — the decision unit.

        Output is 5 rows regardless of how many campaigns are in the account.
        """
        gids = [group_id] if group_id else GROUP_IDS
        out = {}
        for gid in gids:
            if gid not in GROUP_META:
                return {"error": f"unknown group id {gid!r}; expected one of {GROUP_IDS}"}
            prior = _agg(self._by_group[gid], 1, RECENT_START - 1)
            recent = _agg(self._by_group[gid], RECENT_START, N_DAYS)
            info = GROUP_META[gid]
            out[gid] = {
                "name": info["name"], "platform": info["platform"], "kind": info["kind"],
                "n_campaigns": info["n_campaigns"],
                "prior_76d": prior, "recent_14d": recent,
                "roas_change_pct": _change_pct(prior, recent),
                "flags": self.meta.get(gid, {}),
            }
        return out

    def get_group_campaigns(self, group_id, sort_by="spend", limit=10):
        """Drill into a group's individual campaigns. Bounded output.

        `sort_by`: "spend" (largest budgets) or "roas_change" (worst movers first)
        — enough to tell a broad-based decline from a few bad campaigns without
        pulling the whole account into context.
        """
        if group_id not in GROUP_META:
            return {"error": f"unknown group id {group_id!r}; expected one of {GROUP_IDS}"}
        if sort_by not in ("spend", "roas_change"):
            return {"error": f"unknown sort_by {sort_by!r}; expected 'spend' or 'roas_change'"}
        limit = max(1, min(int(limit), MAX_DRILLDOWN))

        items = []
        for c in BY_GROUP[group_id]:
            rows = self._by_campaign[c.id]
            prior = _agg(rows, 1, RECENT_START - 1)
            recent = _agg(rows, RECENT_START, N_DAYS)
            items.append({
                "campaign_id": c.id, "name": c.name,
                "daily_spend": recent["daily_spend"],
                "recent_roas": recent["roas"],
                "roas_change_pct": _change_pct(prior, recent),
            })

        key = (lambda x: -x["daily_spend"]) if sort_by == "spend" else \
              (lambda x: (x["roas_change_pct"] is None, x["roas_change_pct"] or 0))
        items.sort(key=key)
        return {
            "group_id": group_id, "n_campaigns": len(items),
            "sorted_by": sort_by, "showing": min(limit, len(items)),
            "campaigns": items[:limit],
        }

    def get_benchmarks(self):
        return BENCHMARKS

    # ---- modelling ----
    def _curve(self, group_id):
        """Group response curve, fitted once per env and cached.

        Fitted on campaign-days over the PRIOR window only: the recent window is
        where scenario effects live, and fitting on it would let a tracking
        outage or a creative collapse masquerade as the audience's shape.
        """
        if group_id in self._curves:
            return self._curves[group_id]
        pts = [(r["spend"], r["revenue"]) for r in self._by_group[group_id]
               if r["day"] < RECENT_START]
        curve = fit_response_curve(pts)
        prior = _agg(self._by_group[group_id], 1, RECENT_START - 1)
        curve = calibrate_to_group(curve, prior["daily_spend"], prior["revenue"] / max(RECENT_START - 1, 1))
        self._curves[group_id] = curve
        return curve

    def forecast_impact(self, source_campaign, target_campaign, shift_pct):
        """Model-based forecast of moving budget between two groups.

        Fits revenue = a * spend^b per group and evaluates the move on the curve,
        so saturation is priced in: taking budget off a saturated group costs
        less than its average ROAS implies, and adding to one earns less.
        Supersedes forecast_roas, which assumed a flat marginal return.
        """
        for gid in (source_campaign, target_campaign):
            if gid not in GROUP_META:
                return {"error": f"unknown group id {gid!r}; expected one of {GROUP_IDS}"}
        if source_campaign == target_campaign:
            return {"error": "source and target are the same group"}

        m = self.get_campaign_metrics()
        src_spend = m[source_campaign]["recent_14d"]["daily_spend"]
        tgt_spend = m[target_campaign]["recent_14d"]["daily_spend"]
        moved = src_spend * shift_pct / 100.0

        src_curve, tgt_curve = self._curve(source_campaign), self._curve(target_campaign)
        lost = src_curve.revenue_at(src_spend) - src_curve.revenue_at(src_spend - moved)
        gained = tgt_curve.revenue_at(tgt_spend + moved) - tgt_curve.revenue_at(tgt_spend)

        confidence = min(src_curve.r2, tgt_curve.r2)
        return {
            "moved_daily_usd": round(moved, 2),
            "expected_daily_revenue_delta": round(gained - lost, 2),
            "source_revenue_lost": round(lost, 2),
            "target_revenue_gained": round(gained, 2),
            "source_curve": {"group": source_campaign, **src_curve.as_dict(),
                             "marginal_roas": round(src_curve.marginal_roas(src_spend), 3)},
            "target_curve": {"group": target_campaign, **tgt_curve.as_dict(),
                             "marginal_roas": round(tgt_curve.marginal_roas(tgt_spend), 3)},
            "confidence": round(confidence, 3),
            "confidence_note": ("both curves fit well" if confidence >= 0.7 else
                                "LOW — at least one curve is poorly identified; treat the "
                                "delta as directional, not a point estimate"),
            "method": "OLS on log(revenue) ~ log(spend) over prior-window campaign-days",
        }

    def diagnose_drivers(self, group_id):
        """Decompose a group's recent ROAS move into what actually caused it.

        ROAS is revenue/spend, and revenue = spend x ctr x cvr x aov (over the
        impression funnel). So a ROAS move decomposes into four readable causes,
        which map to four different fixes:

          ctr  down  -> the ad stopped earning attention   -> CREATIVE
          cvr  down  -> the click stopped converting       -> TARGETING
          aov  down  -> the buyer got cheaper              -> MIX / OFFER
          saturation -> spend outran the audience          -> BUDGET

        Returns contributions in log space, where the factors are additive and
        therefore sum to the total move.
        """
        if group_id not in GROUP_META:
            return {"error": f"unknown group id {group_id!r}; expected one of {GROUP_IDS}"}

        prior = _agg(self._by_group[group_id], 1, RECENT_START - 1)
        recent = _agg(self._by_group[group_id], RECENT_START, N_DAYS)

        def ratio(k):
            return (recent[k] / prior[k]) if prior[k] else 1.0

        aov_prior = prior["revenue"] / prior["conversions"] if prior["conversions"] else 0.0
        aov_recent = recent["revenue"] / recent["conversions"] if recent["conversions"] else 0.0
        aov_ratio = (aov_recent / aov_prior) if aov_prior else 1.0

        curve = self._curve(group_id)
        drivers = {
            "creative": {"metric": "ctr", "ratio": round(ratio("ctr"), 3),
                         "change_pct": round((ratio("ctr") - 1) * 100, 1),
                         "fix": "refresh the ad creative"},
            "targeting": {"metric": "cvr", "ratio": round(ratio("cvr"), 3),
                          "change_pct": round((ratio("cvr") - 1) * 100, 1),
                          "fix": "re-target: the audience is converting worse"},
            "offer_mix": {"metric": "aov", "ratio": round(aov_ratio, 3),
                          "change_pct": round((aov_ratio - 1) * 100, 1),
                          "fix": "check offer/product mix"},
            "budget": {"metric": "elasticity", "ratio": round(curve.b, 3),
                       "change_pct": None,
                       "fix": ("headroom to scale" if curve.b >= 0.85 else
                               "at/near saturation — more budget will not help")},
        }
        # --- richer signals: what separates look-alike drops ---------------
        # saturation (frequency up), landing (bounce up, sessions steady),
        # auction (cpm up), and budget-cap (pacing at the ceiling).
        freq_r, bounce_r, cpm_r = ratio("frequency"), ratio("bounce_rate"), ratio("cpm")
        drivers.update({
            "saturation_audience": {"metric": "frequency", "ratio": round(freq_r, 3),
                                    "change_pct": round((freq_r - 1) * 100, 1),
                                    "fix": "audience saturating — impressions/user rising; rotate or widen it"},
            "landing": {"metric": "bounce_rate", "ratio": round(bounce_r, 3),
                        "change_pct": round((bounce_r - 1) * 100, 1),
                        "fix": "landing page/checkout is turning real visitors away"},
            "auction": {"metric": "cpm", "ratio": round(cpm_r, 3),
                        "change_pct": round((cpm_r - 1) * 100, 1),
                        "fix": "auction cost rose — competitor pressure, not your creative"},
            "pacing": {"metric": "pacing", "ratio": round(recent["pacing"], 3),
                       "change_pct": None,
                       "fix": ("at the budget cap — raise budget to capture demand"
                               if recent["pacing"] >= 0.95 else "budget headroom remains")},
        })
        ranked = sorted(
            (k for k in ("creative", "targeting", "offer_mix")),
            key=lambda k: drivers[k]["ratio"])
        worst = ranked[0]
        # disambiguation the funnel alone can't do: a CVR/conversions collapse is
        # a TRACKING outage when sessions & bounce are steady, but a LANDING break
        # when bounce spikes while sessions hold. `ratio()` on a count field
        # compares window SUMS (14d vs 76d), so sessions needs a per-DAY ratio.
        rows_g = self._by_group[group_id]
        rd = len({r["day"] for r in rows_g if RECENT_START <= r["day"] <= N_DAYS}) or 1
        pd = len({r["day"] for r in rows_g if 1 <= r["day"] <= RECENT_START - 1}) or 1
        sess_r = ((recent["sessions"] / rd) / (prior["sessions"] / pd)) if prior["sessions"] else 1.0
        conv_r = ratio("cvr") * ratio("ctr")
        if bounce_r > 1.4 and conv_r < 0.75 and sess_r > 0.85:
            disambig = "conversions collapsed but sessions held and bounce SPIKED -> landing-page/checkout break, not tracking."
        elif conv_r < 0.45 and sess_r > 0.85 and bounce_r < 1.25:
            disambig = "conversions near-zero while clicks, sessions AND bounce are all normal -> measurement/tracking outage, not a real drop."
        elif freq_r > 1.3 and ratio("cvr") < 0.9:
            disambig = "frequency climbing while CVR softens -> audience saturation, not a targeting error."
        elif cpm_r > 1.25:
            disambig = "CPM rose sharply -> auction/competitor pressure inflating cost, creative is fine."
        elif recent["pacing"] >= 0.95:
            disambig = "pacing is at the budget ceiling -> capped; increase budget rather than shift it."
        elif aov_ratio < 0.72 and ratio("ctr") > 0.9 and ratio("cvr") > 0.9:
            disambig = "clicks and conversions are healthy but revenue-per-conversion collapsed -> a downstream funnel/value leak, not an ad problem; hold budget and escalate."
        else:
            disambig = None
        return {
            "group_id": group_id,
            "roas_change_pct": _change_pct(prior, recent),
            "drivers": drivers,
            "primary_driver": worst if drivers[worst]["ratio"] < 0.9 else None,
            "elasticity_reading": interpret_elasticity(curve.b),
            "signals": {"frequency": recent["frequency"], "bounce_rate": recent["bounce_rate"],
                        "cpm": recent["cpm"], "cpc": recent["cpc"], "cpa": recent["cpa"],
                        "pacing": recent["pacing"], "sessions_ratio": round(sess_r, 3)},
            "disambiguation": disambig,
            "note": ("No single funnel driver moved much — if ROAS still fell, look for "
                     "measurement or seasonality before touching budget."
                     if drivers[worst]["ratio"] >= 0.9 else
                     f"{worst} is the largest mover ({drivers[worst]['change_pct']:+.1f}%)."),
        }

    def forecast_roas(self, source_campaign, target_campaign, shift_pct):
        """LEGACY naive forecaster: moved dollars earn 90% of target's recent ROAS.

        Superseded by `forecast_impact`, which fits a real response curve. Kept
        because the mock heuristic baseline calls it — it is deliberately the
        *naive* comparator and is no longer exposed to the LLM.
        """
        m = self.get_campaign_metrics()
        if source_campaign not in m or target_campaign not in m:
            return {"error": "unknown group id"}
        src, tgt = m[source_campaign]["recent_14d"], m[target_campaign]["recent_14d"]
        moved_daily = src["daily_spend"] * shift_pct / 100.0
        lost = moved_daily * src["roas"]
        gained = moved_daily * tgt["roas"] * 0.9
        return {
            "moved_daily_usd": round(moved_daily, 2),
            "expected_daily_revenue_delta": round(gained - lost, 2),
            "assumption": "marginal ROAS = 90% of target recent ROAS (naive; replace per-architecture)",
        }

    def find_opportunities(self, limit=5):
        """Rank audiences by whether they deserve a campaign they don't have.

        Cuts the account by SEGMENT rather than by group. A segment can span many
        groups and be a rounding error inside each, so an audience converting far
        above its norm is invisible in the group rollup — which is what every
        other tool reads. This is the only view that can see it.

        An opportunity is an audience that is (a) performing well now, (b)
        improving, and (c) under-invested. All three matter: a good segment that
        already has the budget is not an opportunity, and a rising segment with
        bad economics is a trap.
        """
        limit = max(1, min(int(limit), MAX_DRILLDOWN))
        total_spend = sum(r["spend"] for r in self.rows if r["day"] >= RECENT_START)

        items = []
        for seg, campaigns in BY_SEGMENT.items():
            rows = [r for c in campaigns for r in self._by_campaign[c.id]]
            prior = _agg(rows, 1, RECENT_START - 1)
            recent = _agg(rows, RECENT_START, N_DAYS)
            if not recent["spend"]:
                continue
            items.append({
                "segment": seg,
                "n_campaigns": len(campaigns),
                "groups": sorted({c.group_id for c in campaigns}),
                "recent_roas": recent["roas"],
                "prior_roas": prior["roas"],
                "roas_change_pct": _change_pct(prior, recent),
                "spend_share_pct": round(100 * recent["spend"] / total_spend, 2) if total_spend else 0.0,
                "daily_spend": recent["daily_spend"],
            })

        account_roas = _agg(self.rows, RECENT_START, N_DAYS)["roas"]
        for it in items:
            beats = it["recent_roas"] > account_roas * 1.15
            rising = (it["roas_change_pct"] or 0) >= 20
            small = it["spend_share_pct"] < 5.0
            it["is_opportunity"] = bool(beats and rising and small)
            if it["is_opportunity"]:
                it["why"] = (f"ROAS {it['recent_roas']} vs account {account_roas} "
                             f"(+{it['roas_change_pct']}% and climbing) on only "
                             f"{it['spend_share_pct']}% of spend — demand is there and unmet")

        items.sort(key=lambda x: (not x["is_opportunity"], -(x["roas_change_pct"] or 0)))
        found = [i for i in items if i["is_opportunity"]]
        return {
            "account_roas": account_roas,
            "n_segments": len(items),
            "opportunities": found[:limit],
            "segments": items[:limit],
            "note": ("No under-invested audience stands out — nothing here justifies a new campaign."
                     if not found else
                     f"{len(found)} audience(s) are outperforming on a small share of spend. "
                     "A new campaign targets demand that already exists; it does not move budget "
                     "off anything that is working."),
        }

    def find_losers(self, limit=5):
        """Rank audiences by whether they're structurally unprofitable — dead weight
        to KILL, not fix. The mirror of find_opportunities: cuts by SEGMENT, so a bad
        audience that is a rounding error inside each group is still visible here.

        A loser is an audience whose ROAS is (a) far below the account and (b) under
        break-even, on (c) non-trivial spend — money that would earn more anywhere
        else, with no creative/tracking/learning story that a fix would rescue.
        """
        limit = max(1, min(int(limit), MAX_DRILLDOWN))
        total_spend = sum(r["spend"] for r in self.rows if r["day"] >= RECENT_START)
        account_roas = _agg(self.rows, RECENT_START, N_DAYS)["roas"]
        items = []
        for seg, campaigns in BY_SEGMENT.items():
            rows = [r for c in campaigns for r in self._by_campaign[c.id]]
            recent = _agg(rows, RECENT_START, N_DAYS)
            if not recent["spend"]:
                continue
            share = round(100 * recent["spend"] / total_spend, 2) if total_spend else 0.0
            dead = bool(recent["roas"] < account_roas * 0.5 and recent["roas"] < 1.0 and share >= 1.0)
            it = {"segment": seg, "n_campaigns": len(campaigns),
                  "groups": sorted({c.group_id for c in campaigns}),
                  "recent_roas": recent["roas"], "spend_share_pct": share,
                  "daily_spend": recent["daily_spend"], "is_loser": dead}
            if dead:
                it["why"] = (f"ROAS {recent['roas']} is far below the account ({account_roas}) and "
                             f"under break-even on {share}% of spend — no creative/tracking fix applies; kill it.")
            items.append(it)
        items.sort(key=lambda x: (not x["is_loser"], x["recent_roas"]))
        found = [i for i in items if i["is_loser"]]
        return {
            "account_roas": account_roas, "n_segments": len(items),
            "losers": found[:limit], "segments": items[:limit],
            "note": ("No structurally dead audience — nothing here is worth killing outright."
                     if not found else
                     f"{len(found)} audience(s) burn spend well below break-even with no fixable "
                     "cause. Pausing them reclaims budget for what works."),
        }

    def recommend_action(self, group_id):
        """Derive the fix a group's evidence implies — deterministically.

        Runs `diagnose_drivers`, then maps the result through `policy.py`. The
        mapping is a lookup, not a judgement, so it is identical every time and
        every recommendation cites its numbers.

        It answers "if this diagnosis is true, what is the fix?" — never "is it
        true?". Check `ambiguous`: when set, the same evidence supports more than
        one story and the call is yours.
        """
        if group_id not in GROUP_META:
            return {"error": f"unknown group id {group_id!r}; expected one of {GROUP_IDS}"}
        drivers = self.diagnose_drivers(group_id)
        rec = recommend_action(drivers, flags=self.meta.get(group_id, {}))
        return {"group_id": group_id, **rec.as_dict()}

    def recommend_portfolio(self, limit=5):
        """Assemble a MULTI-ITEM plan across the whole account — deterministically.

        A real answer to "ROAS dropped, where should the budget go?" is rarely one
        move. This walks every group, derives each group's fixes from
        `recommend_actions` (a group can need several — a tired ad AND a wrong
        audience), then adds any new-campaign opportunities from
        `find_opportunities`. The result is a *plan*: a list of concrete items,
        each an (action, group-or-new-campaign) tied to the number that produced
        it. Diagnosis -> plan is a lookup here, not an LLM judgement, so the same
        account always yields the same plan and every line is auditable.

        Items are one of: refresh_creative / fix_targeting (a broken funnel stage
        on an existing group), increase_budget (demand queued behind a cap), or
        launch_campaign (an under-invested audience worth its own campaign). A
        healthy group contributes nothing — the plan only names what to change.
        """
        items = []
        for gid in GROUP_IDS:
            drivers = self.diagnose_drivers(gid)
            for rec in recommend_actions(drivers, flags=self.meta.get(gid, {})):
                if rec.action == "no_action":
                    continue
                items.append({
                    "group": gid, "action": rec.action, "reason": rec.reason,
                    "evidence": rec.evidence, "ambiguous": rec.ambiguous,
                })
        for opp in self.find_opportunities(limit=limit).get("opportunities", []):
            items.append({
                "group": None, "action": "launch_campaign", "segment": opp["segment"],
                "reason": f"under-invested audience already outperforming — {opp.get('why', '')}",
                "evidence": [f"segment ROAS {opp['recent_roas']} on {opp['spend_share_pct']}% of spend"],
                "ambiguous": False,
            })
        return {
            "n_items": len(items),
            "items": items,
            "note": ("A campaign reallocation is a PLAN, not a single move: fix what is broken "
                     "(creative/targeting/budget) on the groups that moved, and launch into "
                     "demand that already exists. A healthy account returns an empty plan."),
        }

    def propose_reallocation(self, source_campaign, target_campaign, shift_pct):
        """Validates a plan against business constraints. Does NOT execute."""
        violations = []
        if shift_pct > CONSTRAINTS["max_weekly_shift_pct"]:
            violations.append(f"shift {shift_pct}% exceeds max weekly shift {CONSTRAINTS['max_weekly_shift_pct']}%")
        if source_campaign == CONSTRAINTS["brand_group_id"]:
            m = self.get_campaign_metrics(source_campaign)[source_campaign]
            monthly_after = m["recent_14d"]["daily_spend"] * (1 - shift_pct / 100.0) * 30
            if monthly_after < CONSTRAINTS["brand_floor_monthly"]:
                violations.append(
                    f"brand group would fall to ${monthly_after:,.0f}/mo, below the "
                    f"${CONSTRAINTS['brand_floor_monthly']:,.0f}/mo floor")
        flags = self.meta.get(source_campaign, {})
        if flags.get("last_edited_days_ago", 99) <= CONSTRAINTS["learning_phase_days"]:
            violations.append(f"{source_campaign} edited {flags['last_edited_days_ago']}d ago — inside learning phase")
        return {"valid": not violations, "violations": violations}

    def apply_reallocation(self, source_campaign, target_campaign, shift_pct, approved_by):
        """Sandbox execution — appends to an executions ledger, returns manifest id."""
        RUNS_DIR.mkdir(exist_ok=True)
        manifest = {
            "manifest_id": f"{self.scenario_id}-{int(time.time())}",
            "scenario": self.scenario_id, "source": source_campaign,
            "target": target_campaign, "shift_pct": shift_pct,
            "approved_by": approved_by, "ts": time.time(),
        }
        with open(RUNS_DIR / "executions.jsonl", "a") as f:
            f.write(json.dumps(manifest) + "\n")
        return {"status": "executed_sandbox", "manifest_id": manifest["manifest_id"]}

    def send_approval_request(self, plan_summary):
        """Stub human gate — auto-approves in harness mode. T4 replaces this with Slack/email."""
        return {"status": "approved", "approver": "harness-auto", "note": "replace with real gate in Track 4"}

    # ---- dispatch for the tool-calling loop ----
    def call(self, name, args):
        fn = getattr(self, name)
        result = fn(**args)
        self.tool_log.append({"tool": name, "args": args})
        return result


OPENAI_TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "get_campaign_metrics",
        "description": ("Prior-76-day vs recent-14-day metrics (spend, ROAS, CTR, CVR, flags) per campaign "
                        "GROUP — the unit budget decisions are made in. Returns all 5 groups by default, "
                        "each rolling up dozens of campaigns."),
        "parameters": {"type": "object", "properties": {
            "group_id": {"type": ["string", "null"], "description": "G1..G5, or null for all groups"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "get_group_campaigns",
        "description": ("Drill into the individual campaigns inside one group — use to check whether a group's "
                        "move is broad-based or driven by a few campaigns. Bounded: returns at most 25."),
        "parameters": {"type": "object", "properties": {
            "group_id": {"type": "string", "description": "G1..G5"},
            "sort_by": {"type": "string", "enum": ["spend", "roas_change"],
                        "description": "'spend' = largest budgets first; 'roas_change' = worst movers first"},
            "limit": {"type": "number", "description": "how many campaigns to return (max 25, default 10)"}},
            "required": ["group_id"]}}},
    {"type": "function", "function": {
        "name": "get_benchmarks",
        "description": "Industry benchmark ROAS by channel/kind. Every value carries a source tag.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "forecast_impact",
        "description": ("Model-based forecast of moving shift_pct%% of a source group's budget to a target "
                        "group. Fits a response curve (revenue = a * spend^b) per group from history, so "
                        "saturation is priced in: it returns the expected daily revenue delta, each group's "
                        "elasticity and marginal ROAS, and a confidence score. Prefer this over average ROAS "
                        "— a group can have high average ROAS and almost no headroom."),
        "parameters": {"type": "object", "properties": {
            "source_campaign": {"type": "string", "description": "source group id, G1..G5"},
            "target_campaign": {"type": "string", "description": "target group id, G1..G5"},
            "shift_pct": {"type": "number"}}, "required": ["source_campaign", "target_campaign", "shift_pct"]}}},
    {"type": "function", "function": {
        "name": "diagnose_drivers",
        "description": ("Decompose a group's recent ROAS move into its causes: creative (ctr), targeting (cvr), "
                        "offer mix (aov), and budget saturation (elasticity). Use this to tell WHICH fix a "
                        "problem needs — a ctr collapse is a creative problem, not a budget one."),
        "parameters": {"type": "object", "properties": {
            "group_id": {"type": "string", "description": "G1..G5"}}, "required": ["group_id"]}}},
    {"type": "function", "function": {
        "name": "find_opportunities",
        "description": ("Rank audiences (segments) by whether they deserve a campaign they do not have. "
                        "Cuts the account by AUDIENCE instead of by group — a segment can be a rounding "
                        "error inside every group and still be the best thing in the account, which the "
                        "group rollup physically cannot show. Use when asked what to LAUNCH, or when the "
                        "groups look healthy but you suspect unmet demand."),
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "number", "description": "how many segments to return (max 25, default 5)"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "find_losers",
        "description": ("Rank audiences (segments) by whether they are structurally unprofitable — dead "
                        "weight to KILL, not fix. The mirror of find_opportunities: cuts by AUDIENCE, so a "
                        "loser that is a rounding error inside every group is still visible. Use when a "
                        "segment burns spend far below break-even with no creative/tracking story to fix."),
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "number", "description": "how many segments to return (max 25, default 5)"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "recommend_action",
        "description": ("Derive the fix a group's evidence implies, deterministically (diagnosis -> action is a "
                        "lookup, not a guess). Returns a candidate action, the numbers behind it, and an "
                        "`ambiguous` flag. It assumes the diagnosis is TRUE — it cannot tell a real audience "
                        "collapse from a broken tracking pixel. Judging that is your job."),
        "parameters": {"type": "object", "properties": {
            "group_id": {"type": "string", "description": "G1..G5"}}, "required": ["group_id"]}}},
    {"type": "function", "function": {
        "name": "recommend_portfolio",
        "description": ("Derive a MULTI-ITEM plan for the whole account in one call: every group's "
                        "funnel fixes (a group can need both a creative refresh AND a targeting fix), "
                        "budget-cap increases, plus new-campaign opportunities. Use when the answer is "
                        "'do several things', not one move. Returns a list of items, each with the "
                        "evidence behind it; a healthy account returns an empty plan."),
        "parameters": {"type": "object", "properties": {
            "limit": {"type": "number", "description": "max new-campaign opportunities to include (default 5)"}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "propose_reallocation",
        "description": ("Validate a reallocation against business constraints (brand floor, max shift, "
                        "learning phase). Does not execute."),
        "parameters": {"type": "object", "properties": {
            "source_campaign": {"type": "string", "description": "source group id, G1..G5"},
            "target_campaign": {"type": "string", "description": "target group id, G1..G5"},
            "shift_pct": {"type": "number"}}, "required": ["source_campaign", "target_campaign", "shift_pct"]}}},
]
