"""H1-1 — memory store: decay math, contradiction demotion, preference staleness."""
import pytest

from tracks.track1.memory_store import (Memory, MemoryStore, contradicts, decayed_weight,
                                  is_preference_stale)


def _store():
    return MemoryStore(db_path=":memory:", half_life=3, stale_after=4, expire_floor=0.15)


# ------------------------------------------------------------------ decay math

def test_decay_half_life():
    assert decayed_weight(1.0, 0, 3) == 1.0
    assert decayed_weight(1.0, 3, 3) == pytest.approx(0.5)
    assert decayed_weight(1.0, 6, 3) == pytest.approx(0.25)


def test_decay_negative_age_clamped():
    assert decayed_weight(1.0, -5, 3) == 1.0


def test_decay_zero_half_life_no_decay():
    assert decayed_weight(0.8, 10, 0) == 0.8


# ------------------------------------------------------------------ staleness

def test_preference_staleness_boundary():
    assert not is_preference_stale(1, 5, 4)   # age exactly 4 -> not yet stale
    assert is_preference_stale(1, 6, 4)        # age 5 -> stale


def test_preference_confirm_resets_clock():
    s = _store()
    pid = s.add("preference", "never cut brand", session=1)
    m = s.get(pid)
    assert m.stale(current_session=6)          # age 5 > 4
    s.confirm_preference(pid, session=6)
    assert not s.get(pid).stale(current_session=6)


def test_preferences_never_expire_only_flag():
    s = _store()
    s.add("preference", "conservative shifts", session=1)
    log = s.apply_forgetting(current_session=20)
    assert log["expired_outcomes"] == []
    assert len(log["stale_preferences"]) == 1
    assert s.list_active()[0].kind == "preference"  # still active


# ------------------------------------------------------------------ contradiction

def test_contradicts_pure_function():
    a = Memory(1, "outcome", "shift to G5 worked", "G5", "shift_to_G5", 1, 1, 1.0, 1.0, +1, "active")
    b = Memory(2, "outcome", "shift to G5 backfired", "G5", "shift_to_G5", 2, 2, 1.0, 1.0, -1, "active")
    assert contradicts(b, a)
    # different topic -> not a contradiction
    c = Memory(3, "outcome", "other", "G5", "increase_G5", 2, 2, 1.0, 1.0, -1, "active")
    assert not contradicts(c, a)


def test_new_outcome_demotes_contradicted_old():
    s = _store()
    old = s.add("outcome", "shift to G5 worked", session=1, campaign_id="G5",
                topic="shift_to_G5", polarity=+1)
    new = s.add("outcome", "shift to G5 backfired", session=2, campaign_id="G5",
                topic="shift_to_G5", polarity=-1)
    assert s.get(old).status == "demoted"
    assert s.get(new).status == "active"


def test_non_contradicting_outcome_keeps_both():
    s = _store()
    a = s.add("outcome", "shift to G5 worked", session=1, campaign_id="G5",
              topic="shift_to_G5", polarity=+1)
    b = s.add("outcome", "shift to C3 worked", session=2, campaign_id="G3",
              topic="shift_to_G3", polarity=+1)
    assert s.get(a).status == "active"
    assert s.get(b).status == "active"


# ------------------------------------------------------------------ forgetting pass

def test_old_outcome_expires_below_floor():
    s = _store()
    oid = s.add("outcome", "ancient CPC insight", session=1, campaign_id="G1",
                topic="cpc", polarity=+1, outcome_weight=1.0)
    # weight at session 13 = 0.5 ** (12/3) = 0.0625 < 0.15 floor
    log = s.apply_forgetting(current_session=13)
    assert oid in log["expired_outcomes"]
    assert s.get(oid).status == "expired"


def test_recent_outcome_survives():
    s = _store()
    oid = s.add("outcome", "recent lesson", session=5, campaign_id="G1",
                topic="cpc", polarity=+1)
    log = s.apply_forgetting(current_session=6)
    assert oid not in log["expired_outcomes"]
    assert s.get(oid).status == "active"


def test_persistence_roundtrip(tmp_path):
    path = str(tmp_path / "mem.db")
    s = MemoryStore(db_path=path)
    s.add("preference", "never cut brand", session=1, campaign_id="G2")
    s.close()
    s2 = MemoryStore(db_path=path)
    assert len(s2.list_all()) == 1
    assert s2.list_all()[0].text == "never cut brand"
