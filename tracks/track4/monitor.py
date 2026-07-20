"""H3-3 — post-execution monitor, guardrail rollback, notifications (Track 4).

Monitor: simulate 14 post-days with the shift applied — moved dollars earn the
target's ROAS x 0.9 with deterministic noise. Guardrail: if realized daily
revenue delta < 70% of the forecast, auto-rollback (reverse the manifest) and
notify. Deterministic (seed derived from the scenario id) so mock runs are stable.
"""
import json
import random
import time

GUARDRAIL_RATIO = 0.70
POST_DAYS = 14


def _campaign_roas(env, cid):
    m = env.get_campaign_metrics(cid)
    return m[cid]["recent_14d"]["roas"]


def monitor_outcome(env, plan: dict, forecast: dict, seed: int,
                    guardrail: float = GUARDRAIL_RATIO) -> dict:
    """Return realized vs forecast and whether the guardrail was breached."""
    source, target = plan.get("source_campaign"), plan.get("target_campaign")
    moved_daily = forecast.get("moved_daily_usd", 0.0)
    forecast_delta = forecast.get("expected_daily_revenue_delta", 0.0)

    src_roas = _campaign_roas(env, source) if source else 0.0
    tgt_roas = _campaign_roas(env, target) if target else 0.0

    rng = random.Random(seed)
    noise = rng.uniform(0.65, 1.15)                 # realized efficiency of moved $
    gained = moved_daily * tgt_roas * 0.9 * noise
    lost = moved_daily * src_roas
    realized_delta = round(gained - lost, 2)

    # breach if forecast was positive but realized fell short of 70% of it
    breached = forecast_delta > 0 and realized_delta < guardrail * forecast_delta
    ratio = round(realized_delta / forecast_delta, 3) if forecast_delta else None
    return {"post_days": POST_DAYS, "forecast_delta": round(forecast_delta, 2),
            "realized_delta": realized_delta, "realized_vs_forecast": ratio,
            "noise_factor": round(noise, 3), "guardrail_ratio": guardrail,
            "breached": breached}


def reverse_manifest(env, manifest: dict, approved_by: str = "auto-rollback") -> dict:
    """Reverse an executed reallocation by applying the opposite shift."""
    rollback = env.apply_reallocation(
        source_campaign=manifest.get("target"), target_campaign=manifest.get("source"),
        shift_pct=manifest.get("shift_pct"), approved_by=approved_by)
    rollback["reverses"] = manifest.get("manifest_id")
    return rollback


def notify(out_dir, scenario: str, kind: str, message: str, path=None) -> dict:
    """Append a human-facing notification (Slack/email swap point)."""
    p = path or (out_dir / "notifications.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    entry = {"scenario": scenario, "type": kind, "message": message, "ts": time.time()}
    # SWAP: send this to a real Slack/email channel instead of the file append.
    with open(p, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry
