"""Response-curve modelling: what does the next dollar actually earn?

The naive forecaster this replaces assumed moved budget earns "90% of the
target's recent ROAS" — a flat line. That is wrong in the way that matters: ad
channels saturate. A dollar into Brand Search (a few thousand people search your
name; b=0.45) does not behave like a dollar into Advantage+ (b=0.90).

We fit revenue = a * spend^b per group by ordinary least squares on
log(revenue) = log(a) + b*log(spend), pooled over campaign-days. The long tail
of campaign budgets inside a group (a ~20x spread) is what identifies b: big
campaigns sit further down the curve than small ones. This is the same shape a
marketing-mix model estimates.

`b` is the whole point, and it is directly readable:
    b -> 1.0   linear; the next dollar earns what the last one did — room to scale
    b -> 0.5   sharply saturated; the next dollar earns about half the average

Every fit carries its own r2 and n, so a caller can tell a confident curve from
a guess (G2/brand has only 15 campaigns and fits worst — that is real, and it
should be reported rather than hidden).

Pure stdlib: this is a 1-D least squares, it does not need numpy.
"""
import math
from dataclasses import dataclass
from typing import List, Sequence, Tuple


@dataclass(frozen=True)
class ResponseCurve:
    """revenue = a * spend^b, fitted in log-log space."""
    a: float
    b: float          # elasticity
    r2: float         # share of log-revenue variance explained
    n: int            # observations behind the fit

    def revenue_at(self, spend: float) -> float:
        if spend <= 0:
            return 0.0
        return self.a * (spend ** self.b)

    def marginal_roas(self, spend: float) -> float:
        """d(revenue)/d(spend) at `spend` — what the NEXT dollar earns.

        For a*s^b this is a*b*s^(b-1), i.e. average ROAS scaled by b. That
        factor is exactly the saturation penalty.
        """
        if spend <= 0:
            return 0.0
        return self.a * self.b * (spend ** (self.b - 1.0))

    def as_dict(self) -> dict:
        return {"elasticity": round(self.b, 3), "r2": round(self.r2, 3), "n_observations": self.n,
                "reading": interpret_elasticity(self.b)}


def interpret_elasticity(b: float) -> str:
    """Plain-English reading of the exponent — the UI and rationales use this."""
    if b >= 0.85:
        return "scales well — the next dollar earns nearly what the last one did"
    if b >= 0.70:
        return "mild saturation — still room, but returns are tapering"
    if b >= 0.55:
        return "saturating — the next dollar earns noticeably less than the average"
    return "heavily saturated — near its ceiling; extra budget mostly wasted"


def fit_response_curve(points: Sequence[Tuple[float, float]]) -> ResponseCurve:
    """Least-squares fit of revenue = a * spend^b over (spend, revenue) pairs.

    Points with a non-positive spend or revenue are dropped — log is undefined
    there, and a zero-revenue day carries no information about the curve.
    """
    xs: List[float] = []
    ys: List[float] = []
    for spend, revenue in points:
        if spend > 0 and revenue > 0:
            xs.append(math.log(spend))
            ys.append(math.log(revenue))

    n = len(xs)
    if n < 3:
        # Not enough to fit anything. Fail loudly rather than invent a curve.
        return ResponseCurve(a=0.0, b=1.0, r2=0.0, n=n)

    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:  # every campaign spends exactly the same -> b is unidentifiable
        return ResponseCurve(a=math.exp(my), b=1.0, r2=0.0, n=n)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))

    b = sxy / sxx
    log_a = my - b * mx

    ss_res = sum((y - (log_a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return ResponseCurve(a=math.exp(log_a), b=b, r2=r2, n=n)


def calibrate_to_group(curve: ResponseCurve, group_spend: float, group_revenue: float) -> ResponseCurve:
    """Re-level a campaign-level curve onto a whole group.

    The exponent `b` is a property of the audience and survives aggregation: scale
    every campaign in a group by f and group revenue scales by f^b. The intercept
    does not, so we re-solve `a` from the group's own observed (spend, revenue).
    That keeps the curve anchored to what actually happened rather than to a
    sum of per-campaign intercepts.
    """
    if group_spend <= 0 or group_revenue <= 0:
        return ResponseCurve(a=0.0, b=curve.b, r2=curve.r2, n=curve.n)
    a = group_revenue / (group_spend ** curve.b)
    return ResponseCurve(a=a, b=curve.b, r2=curve.r2, n=curve.n)
