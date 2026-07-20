"""Make the repo root importable so `from config import ...` works from tests/."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# --- the build's canary ----------------------------------------------------
# The mock heuristic is rule-based and the dataset is seeded, so its score over
# the 10 scenarios is exact and reproducible. Pinning it in one place means drift
# in datagen, scenarios, tools, or scoring fails loudly instead of quietly moving
# every published number.
#
# Changing this value is a deliberate act: it asserts the harness *should* score
# differently now. When it changes, re-run the live benchmarks — every headline
# figure (baseline / +rules / society / memory curves) derives from this dataset
# and is stale the moment this moves.
#
# History:
#   5.8 — 5-campaign account.
#   5.4 — 300-campaign portfolio rolled up into 5 groups. Rolling up averages out
#         the per-campaign noise that used to drag S04's cvr_ratio under the
#         heuristic's 0.78 threshold by luck; it now misclassifies honestly.
#   4.6 — the action space grew past budget moves (refresh_creative, fix_targeting,
#         ...). The heuristic thinks every problem is a budget problem, so it cannot
#         express the right fix for S01/S04 at all. The drop is the point: that
#         worldview is the strawman this project exists to beat.
#   4.8 — S11 (emerging audience) added, so the total is out of 11, not 10. The
#         heuristic scrapes partial credit there for doing nothing about a
#         segment it cannot see.
#   5.2 — richer metrics added (frequency/cpm/pacing/bounce) and two new traps,
#         S12 (landing-page break) + S13 (funnel leak), so the total is out of 13.
#         The heuristic scores 0 on both new traps — it has no signal for them —
#         which is the point; the sharpened S05/S09 also shifted its partial credit.
#   5.4 — two more decisions added: S14 (over-invested -> decrease_budget) and S15
#         (structurally dead audience -> pause_campaign), out of 15. The heuristic
#         has no signal for either; it only scrapes partial credit.
MOCK_BASELINE_TOTAL = 5.4


@pytest.fixture
def mock_baseline_total() -> float:
    return MOCK_BASELINE_TOTAL
