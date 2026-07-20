"""Portfolio topology: expand the 5 campaign groups into ~300 live campaigns.

Why this module exists
----------------------
A VP Growth does not reason about 300 campaigns; they reason about 5 *groups*
("is Brand holding? is Prospecting decaying?"). But the account underneath is
genuinely 300 campaigns, and that is where the scaling problem lives: dumping
every campaign into the model's context costs ~32k tokens at N=300 (see
`runs/scaling.json`) and breaks outright past it.

So the decision unit is the GROUP, and campaigns are the drill-down. `config`
declares the shape (knobs); this module derives the topology (facts). Keeping
them apart means the account can be resized without touching any agent code.

Everything here is deterministic given `SEED` — same portfolio every run.
"""
import random
from dataclasses import dataclass
from typing import Dict, List

from cmo.config import GROUPS, SEED


@dataclass(frozen=True)
class Campaign:
    """One live campaign — a leaf under a group."""
    id: str
    name: str
    group_id: str
    platform: str
    kind: str
    daily_spend: float
    ctr: float
    cvr: float
    aov: float
    elasticity: float      # inherited from the group: revenue ~ spend^elasticity
    group_ref_spend: float  # the group's mean campaign spend — the curve's origin
    segment: str           # the audience this campaign targets, e.g. "Interest — Fitness"
    frequency: float       # avg impressions per unique user (impressions/reach)
    bounce: float          # baseline share of landing sessions that bounce
    daily_budget: float    # this campaign's daily budget cap


# The audience each campaign targets. These double as the account's segment
# dimension: many campaigns across several groups can chase the same audience, and
# a segment's performance is only visible by aggregating across them — never from
# the group rollup, where a small segment is a rounding error. That is exactly the
# blind spot `find_opportunities` exists to cover.
#
# Cycled, not random — deterministic.
_VARIANTS: Dict[str, List[str]] = {
    "prospecting": ["Lookalike 1%", "Lookalike 3%", "Lookalike 5%", "Interest — Fitness",
                    "Interest — Outdoors", "Broad", "Advantage+ Audience", "Video Views",
                    "Carousel", "Collection"],
    "brand": ["Exact", "Phrase", "Core Terms", "Misspellings", "Competitor Conquest"],
    "retargeting": ["7d Visitors", "14d Visitors", "30d Visitors", "Cart Abandoners",
                    "Product Viewers", "Past Purchasers", "Engaged Video"],
    "nonbrand": ["Category — Broad", "Category — Exact", "Long Tail", "DSA",
                 "Shopping — All", "Competitor", "Generic Terms"],
}


def _spend_weights(n: int, rng: random.Random) -> List[float]:
    """Long-tailed budget split summing to 1.0.

    Real accounts are never uniform: a handful of campaigns carry most of the
    spend and a long tail carries the rest. Lognormal weights reproduce that
    shape; without it, every campaign would look identical and drill-down would
    be pointless.
    """
    raw = [rng.lognormvariate(0.0, 0.7) for _ in range(n)]
    total = sum(raw)
    return [w / total for w in raw]


def build_campaigns(seed: int = SEED) -> List[Campaign]:
    """Expand every group in `config.GROUPS` into its leaf campaigns.

    A group's `daily_spend` is split across its campaigns; per-campaign rates
    (ctr/cvr/aov) jitter around the group's profile so the rollup still lands on
    the declared group numbers while individual campaigns differ.
    """
    campaigns: List[Campaign] = []
    for g in GROUPS:
        rng = random.Random(f"{seed}:{g['id']}")  # per-group stream: adding a group can't reshuffle the others
        variants = _VARIANTS[g["kind"]]
        n = g["n_campaigns"]
        weights = _spend_weights(n, rng)
        # The curve's origin: a campaign spending the group average is "at par".
        # Bigger campaigns sit further down the diminishing-returns curve, which
        # is what makes the elasticity visible in the data at all.
        ref_spend = g["daily_spend"] / n
        group_budget = g["daily_spend"] * g["budget_mult"]
        for i, weight in enumerate(weights):
            variant = variants[i % len(variants)]
            suffix = f" {i // len(variants) + 1}" if n > len(variants) else ""
            campaigns.append(Campaign(
                id=f"{g['id']}-{i + 1:03d}",
                name=f"{g['name']} · {variant}{suffix}",
                group_id=g["id"],
                platform=g["platform"],
                kind=g["kind"],
                daily_spend=round(g["daily_spend"] * weight, 2),
                ctr=g["ctr"] * rng.gauss(1.0, 0.12),
                cvr=g["cvr"] * rng.gauss(1.0, 0.12),
                aov=g["aov"] * rng.gauss(1.0, 0.08),
                elasticity=g["elasticity"],
                group_ref_spend=round(ref_spend, 2),
                segment=variant,
                frequency=max(1.05, g["frequency"] * rng.gauss(1.0, 0.10)),
                bounce=min(0.85, max(0.15, g["bounce"] * rng.gauss(1.0, 0.08))),
                daily_budget=round(group_budget * weight, 2),
            ))
    return campaigns


CAMPAIGNS: List[Campaign] = build_campaigns()

# --- lookups (built once; the row aggregations are hot paths) ---

GROUP_IDS: List[str] = [g["id"] for g in GROUPS]
GROUP_META: Dict[str, dict] = {
    g["id"]: {"name": g["name"], "platform": g["platform"], "kind": g["kind"],
              "n_campaigns": g["n_campaigns"], "elasticity": g["elasticity"]}
    for g in GROUPS
}
BY_GROUP: Dict[str, List[Campaign]] = {gid: [] for gid in GROUP_IDS}
for _c in CAMPAIGNS:
    BY_GROUP[_c.group_id].append(_c)

# Segments cut ACROSS groups — the axis the group rollup cannot see.
BY_SEGMENT: Dict[str, List[Campaign]] = {}
for _c in CAMPAIGNS:
    BY_SEGMENT.setdefault(_c.segment, []).append(_c)

SEGMENTS: List[str] = sorted(BY_SEGMENT)


def portfolio_summary() -> dict:
    """Headline shape of the account — used in prompts and the UI."""
    daily = sum(c.daily_spend for c in CAMPAIGNS)
    return {
        "n_groups": len(GROUP_IDS),
        "n_campaigns": len(CAMPAIGNS),
        "daily_spend_usd": round(daily, 2),
        "monthly_spend_usd": round(daily * 30, 2),
        "annual_spend_usd": round(daily * 365, 2),
    }


def account_brief() -> str:
    """One-line account description for agent prompts.

    Derived from the portfolio rather than written down, so the prompt can never
    contradict the numbers the tools return — resizing the account rewrites this
    automatically.
    """
    s = portfolio_summary()
    return (f"our ${s['monthly_spend_usd'] / 1e6:.1f}M/month, {s['n_campaigns']}-campaign account "
            f"(Google + Meta), organised into {s['n_groups']} campaign groups (G1..G5). "
            f"Budget decisions are made at the group level")
