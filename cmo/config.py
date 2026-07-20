"""Shared config for the three-track hackathon foundation."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # repo root (this file lives in cmo/)
DATA_DIR = ROOT / "data"
RUNS_DIR = ROOT / "runs"


def _load_dotenv(path: Path):
    """Minimal .env loader (no python-dotenv dep). Real environment wins:
    values are only applied when the key isn't already set."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and val:
            os.environ.setdefault(key, val)


_load_dotenv(ROOT / ".env")

# --- Qwen LLM provider (OpenAI-compatible mode) ---
# Qwen on Alibaba Cloud Model Studio (Qwen Cloud / DashScope). It speaks the
# OpenAI Chat Completions + tool-calling wire format, so the `openai` SDK is the
# only dependency. VERIFY exact model strings + endpoint in the Model Studio
# console before any live run. Auth: DASHSCOPE_API_KEY.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "dashscope").lower()
QWEN_BASE_URL = os.environ.get(
    "QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
)
QWEN_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
QWEN_API_KEY_ENV = "DASHSCOPE_API_KEY"
MODELS = {
    "orchestrator": os.environ.get("QWEN_ORCH_MODEL", "qwen-plus"),
    "cheap": os.environ.get("QWEN_CHEAP_MODEL", "qwen-flash"),
    "synthesis": os.environ.get("QWEN_MAX_MODEL", "qwen-max"),
}


def _validate_models():
    """Fail closed if a model id isn't a Qwen Cloud slug.

    QWEN_*_MODEL is read from the environment (.env wins over these defaults). A
    dotted / ':'-versioned id left over from another provider would be pointed at
    the Model Studio endpoint, which rejects it as an unknown model far from the
    line that set it. Catch it here, at import, with a message that says what to fix.
    """
    foreign_style = lambda m: m.startswith("qwen.") or ":" in m
    for role, model in MODELS.items():
        if foreign_style(model):
            raise RuntimeError(
                f"{role} model {model!r} is not a Qwen Cloud id. Model Studio ids look "
                f"like 'qwen-plus' / 'qwen-max' / 'qwen-flash'. Fix QWEN_*_MODEL in .env "
                f"or unset them to take the defaults.")


_validate_models()

# --- Simulation shape ---
N_DAYS = 90
WINDOW = 14  # "recent" window where scenario effects are injected (days 77..90)
SEED = 42

# --- Portfolio shape ---
# The account: a mid-market DTC brand spending ~$1.2M/month ($40k/day) across
# ~300 campaigns on Google + Meta.
#
# The VP Growth reasons about 5 campaign GROUPS; each group fans out into dozens
# of live campaigns (see `portfolio.py`). Decisions are made at group level —
# that is what keeps the model's context O(groups) rather than O(campaigns),
# which matters because 300 campaigns is ~32k tokens of raw metrics.
#
# Group daily_spend sums to $40,000/day. Ratios are the account's channel mix.
#
# `elasticity` is the group's diminishing-returns exponent: revenue ~ spend^b.
# b = 1.0 would mean a dollar always earns the same (scale forever); real ad
# channels are well under 1 because campaigns in a group share one finite
# audience — spending more digs deeper into it and converts worse. The spread
# across kinds is the whole reason reallocation is a real decision:
#   brand       0.45  hardest ceiling — only so many people search your name
#   retargeting 0.55  a finite pool of site visitors
#   nonbrand    0.75  broader, but auction prices rise
#   prospecting 0.85+ broadest; Advantage+ (G5) scales best
# Per-group profile. Beyond spend and the ctr/cvr/aov funnel rates, each group
# also declares:
#   frequency   avg impressions per unique user (impressions/reach). Retargeting
#               burns a small audience fast (high freq); brand/search is low.
#   bounce      baseline share of landing sessions that bounce. A landing-page
#               break spikes this while sessions stay normal — the tell that
#               separates a broken page from a broken tracking pixel.
#   budget_mult daily budget cap = daily_spend x this. G5 runs tight (1.06) so it
#               can hit its cap; the rest have headroom.
GROUPS = [
    dict(id="G1", name="Summer Sale — Prospecting", platform="meta", kind="prospecting",
         daily_spend=12000.0, ctr=0.018, cvr=0.030, aov=62.0, n_campaigns=90, elasticity=0.82,
         frequency=2.2, bounce=0.48, budget_mult=1.40),
    dict(id="G2", name="Brand Search", platform="google", kind="brand",
         daily_spend=7000.0, ctr=0.065, cvr=0.055, aov=58.0, n_campaigns=15, elasticity=0.45,
         frequency=1.8, bounce=0.32, budget_mult=1.30),
    dict(id="G3", name="Retargeting", platform="meta", kind="retargeting",
         daily_spend=6000.0, ctr=0.028, cvr=0.048, aov=55.0, n_campaigns=45, elasticity=0.55,
         frequency=4.5, bounce=0.40, budget_mult=1.50),
    dict(id="G4", name="Generic Search", platform="google", kind="nonbrand",
         daily_spend=10000.0, ctr=0.022, cvr=0.020, aov=54.0, n_campaigns=100, elasticity=0.75,
         frequency=1.6, bounce=0.44, budget_mult=1.50),
    dict(id="G5", name="Advantage+ Prospecting", platform="meta", kind="prospecting",
         daily_spend=5000.0, ctr=0.020, cvr=0.033, aov=60.0, n_campaigns=50, elasticity=0.90,
         frequency=2.0, bounce=0.46, budget_mult=1.06),
]
CPM = {"meta": 9.0, "google": 14.0}  # synthetic cost per 1000 impressions

# --- Business constraints (enforced by propose_reallocation) ---
# Dollar figures track the portfolio above: brand runs ~$210k/mo, and the floor
# is the contractual minimum the brand term may never fall below.
CONSTRAINTS = {
    "brand_floor_monthly": 200_000.0,  # G2 monthly spend may never go below this
    "brand_group_id": "G2",
    "max_weekly_shift_pct": 20.0,      # no more than 20% of a group's budget moved per week
    "learning_phase_days": 7,          # groups edited within this window are risky to touch
}

# The action space. A budget move is only one of the things a growth lead can do,
# and for several root causes it is the *wrong* one: creative fatigue is fixed by
# new creative, not by moving money away from a campaign that still works.
ACTIONS = (
    "shift_budget",      # move budget between groups
    "increase_budget",   # add budget to a group with headroom
    "decrease_budget",   # pull budget out of a saturated group
    "refresh_creative",  # the ad stopped earning attention (ctr)
    "fix_targeting",     # the click stopped converting (cvr)
    "fix_landing_page",  # visitors arrive but the page/checkout turns them away (bounce)
    "launch_campaign",   # a gap worth a new campaign
    "pause_campaign",    # a structurally unprofitable segment/campaign — kill it
    "fix_tracking",      # measurement is broken; the data is lying
    "no_action",         # the correct answer more often than instinct suggests
)

DECISION_SCHEMA_HINT = {
    "root_cause": "one of: creative_fatigue | tracking_outage | landing_page_break | "
                  "seasonality | audience_saturation | over_saturation | competitor_pressure | "
                  "winner_opportunity | brand_demand_dip | learning_phase | budget_cap | "
                  "funnel_leak | dead_campaign | emerging_segment | noise",
    "action": "one of: " + " | ".join(ACTIONS),
    "source_campaign": "campaign group id (G1..G5) or null",
    "target_campaign": "campaign group id (G1..G5) or null",
    "shift_pct": "percent of source budget to move (<= 20), or null",
    "rationale": "2-3 sentences, every number traceable to a tool result",
}
