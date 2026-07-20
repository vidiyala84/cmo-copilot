"""Synthetic ad dataset: ~300 campaigns x 90 days. Pure stdlib, deterministic.

Rows are per *campaign* (the leaf), and every row carries its `group_id` so the
tool layer can roll up to the 5 decision units without a second lookup. Scenario
perturbations in `scenarios.py` target a group and hit all of its campaigns.
"""
import csv
import random

from cmo.config import CPM, DATA_DIR, N_DAYS, SEED
from cmo.portfolio import CAMPAIGNS


def generate_base(seed: int = SEED):
    """Rows: day, campaign_id, group_id, name, platform, kind, spend,
    impressions, clicks, conversions, revenue."""
    rng = random.Random(seed)
    # Separate stream for the added metrics (reach/sessions/bounces) so their
    # jitter never perturbs the original spend/ctr/cvr sequence — the existing
    # dataset (and the pinned canary) stays byte-identical.
    rng2 = random.Random(seed + 777)
    rows = []
    for day in range(1, N_DAYS + 1):
        # gentle weekly rhythm: weekends slightly cheaper, slightly lower cvr
        weekend = day % 7 in (0, 6)
        for c in CAMPAIGNS:
            spend = c.daily_spend * rng.gauss(1.0, 0.05)
            impressions = spend / CPM[c.platform] * 1000 * rng.gauss(1.0, 0.04)
            ctr = c.ctr * (0.95 if weekend else 1.0) * rng.gauss(1.0, 0.06)
            clicks = impressions * ctr
            # Diminishing returns. Campaigns in a group share one finite audience,
            # so spending above the group's par digs deeper into it and converts
            # worse. Discounting cvr by (spend/ref)^(b-1) makes revenue scale as
            # spend^b exactly — which is what forecast_impact fits back out.
            saturation = (spend / c.group_ref_spend) ** (c.elasticity - 1.0)
            cvr = c.cvr * saturation * (0.92 if weekend else 1.0) * rng.gauss(1.0, 0.08)
            conversions = clicks * cvr
            revenue = conversions * c.aov * rng.gauss(1.0, 0.05)
            # reach = impressions / frequency (finite audience each impression re-hits);
            # sessions ~ clicks that reach the site; bounces = sessions x bounce rate.
            reach = impressions / (c.frequency * rng2.gauss(1.0, 0.03))
            sessions = clicks * min(1.0, rng2.gauss(0.98, 0.02))
            bounces = sessions * min(0.95, max(0.05, c.bounce * rng2.gauss(1.0, 0.05)))
            rows.append({
                "day": day, "campaign_id": c.id, "group_id": c.group_id, "name": c.name,
                "segment": c.segment,
                "platform": c.platform, "kind": c.kind, "spend": round(spend, 2),
                "impressions": int(impressions), "clicks": round(clicks, 1),
                "conversions": round(conversions, 2), "revenue": round(revenue, 2),
                "reach": int(reach), "sessions": round(sessions, 1), "bounces": round(bounces, 1),
                "budget": c.daily_budget,
            })
    return rows


def write_csv(rows, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    from cmo.portfolio import portfolio_summary

    rows = generate_base()
    out = DATA_DIR / "base_campaigns.csv"
    write_csv(rows, out)
    s = portfolio_summary()
    print(f"portfolio: {s['n_campaigns']} campaigns in {s['n_groups']} groups, "
          f"${s['monthly_spend_usd']:,.0f}/mo")
    print(f"wrote {len(rows)} rows -> {out}")
