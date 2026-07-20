"""H1-1 — memory stores + forgetting policy (Track 1).

Three memory kinds in one SQLite table (`runs/memory.db`):

  preference — durable user rules ("never cut brand below $2k"). Never auto-
               expire, but flagged `stale` past N sessions so the agent can
               re-confirm them.
  outcome    — "we did X and it worked/backfired". Decays by half-life: old
               campaign lessons stop dominating. A new outcome that contradicts
               an active one (same campaign+topic, opposite polarity) demotes
               the old belief instead of silently keeping both.
  episode    — compressed run summaries, for "what did we decide last month".

The forgetting rules are pure functions (`decayed_weight`, `is_preference_stale`,
`contradicts`) so they are unit-testable without touching SQLite.

Schema note: the PRD's core columns are all present; `topic` and `polarity` are
added to make contradiction detection precise ("opposes on same campaign+topic").
"""
import os
import sqlite3
from dataclasses import dataclass
from typing import List, Optional

from cmo.config import RUNS_DIR

# Tunables (env-overridable, per PRD "default 3 sessions, config").
OUTCOME_HALF_LIFE = int(os.environ.get("MEM_OUTCOME_HALF_LIFE", "3"))       # sessions
PREFERENCE_STALE_AFTER = int(os.environ.get("MEM_PREF_STALE_AFTER", "4"))    # sessions
EXPIRE_WEIGHT_FLOOR = float(os.environ.get("MEM_EXPIRE_FLOOR", "0.15"))      # decayed weight

KINDS = ("preference", "outcome", "episode")
STATUSES = ("active", "demoted", "expired")


# ----------------------------------------------------------- pure forgetting math

def decayed_weight(base_weight: float, age_sessions: int, half_life: int = OUTCOME_HALF_LIFE) -> float:
    """Exponential half-life decay. age 0 -> base; age == half_life -> base/2."""
    if half_life <= 0:
        return base_weight
    age = max(0, age_sessions)
    return base_weight * (0.5 ** (age / half_life))


def is_preference_stale(last_confirmed_session: int, current_session: int,
                        stale_after: int = PREFERENCE_STALE_AFTER) -> bool:
    """A preference goes stale once it hasn't been reconfirmed for > N sessions."""
    return (current_session - last_confirmed_session) > stale_after


def contradicts(new: "Memory", old: "Memory") -> bool:
    """Two outcome memories conflict iff same campaign+topic and opposite polarity."""
    return (
        new.kind == "outcome" and old.kind == "outcome"
        and old.status == "active"
        and new.campaign_id == old.campaign_id
        and new.topic == old.topic
        and new.polarity != 0 and old.polarity != 0
        and new.polarity != old.polarity
    )


@dataclass
class Memory:
    id: Optional[int]
    kind: str
    text: str
    campaign_id: Optional[str]
    topic: Optional[str]
    session_created: int
    last_confirmed_session: int
    confidence: float
    outcome_weight: float
    polarity: int          # +1 worked / -1 backfired / 0 n/a
    status: str
    payload: Optional[str] = None   # JSON string: structured rule / learned decision

    # --- derived, given the current session ---
    def effective_weight(self, current_session: int, half_life: int = OUTCOME_HALF_LIFE) -> float:
        if self.kind != "outcome":
            return self.outcome_weight
        return decayed_weight(self.outcome_weight, current_session - self.session_created, half_life)

    def stale(self, current_session: int, stale_after: int = PREFERENCE_STALE_AFTER) -> bool:
        if self.kind != "preference":
            return False
        return is_preference_stale(self.last_confirmed_session, current_session, stale_after)


_COLUMNS = ("id", "kind", "text", "campaign_id", "topic", "session_created",
            "last_confirmed_session", "confidence", "outcome_weight", "polarity",
            "status", "payload")


def _row_to_memory(row) -> Memory:
    return Memory(**{c: row[i] for i, c in enumerate(_COLUMNS)})


class MemoryStore:
    def __init__(self, db_path=None, half_life: int = OUTCOME_HALF_LIFE,
                 stale_after: int = PREFERENCE_STALE_AFTER,
                 expire_floor: float = EXPIRE_WEIGHT_FLOOR):
        if db_path is None:
            RUNS_DIR.mkdir(exist_ok=True)
            db_path = str(RUNS_DIR / "memory.db")
        self.db_path = db_path
        self.half_life = half_life
        self.stale_after = stale_after
        self.expire_floor = expire_floor
        self.conn = sqlite3.connect(db_path)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                text TEXT NOT NULL,
                campaign_id TEXT,
                topic TEXT,
                session_created INTEGER NOT NULL,
                last_confirmed_session INTEGER NOT NULL,
                confidence REAL NOT NULL DEFAULT 1.0,
                outcome_weight REAL NOT NULL DEFAULT 1.0,
                polarity INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                payload TEXT
            )""")
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------------ writes

    def add(self, kind: str, text: str, session: int, campaign_id: Optional[str] = None,
            topic: Optional[str] = None, confidence: float = 1.0,
            outcome_weight: float = 1.0, polarity: int = 0,
            payload: Optional[str] = None) -> int:
        assert kind in KINDS, f"unknown kind {kind}"
        candidate = Memory(None, kind, text, campaign_id, topic, session, session,
                           confidence, outcome_weight, polarity, "active", payload)
        # contradiction handling: demote active outcomes this one opposes
        if kind == "outcome":
            for old in self.list_active():
                if contradicts(candidate, old):
                    self.set_status(old.id, "demoted")
        cur = self.conn.execute(
            "INSERT INTO memories (kind, text, campaign_id, topic, session_created, "
            "last_confirmed_session, confidence, outcome_weight, polarity, status, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (kind, text, campaign_id, topic, session, session, confidence,
             outcome_weight, polarity, "active", payload))
        self.conn.commit()
        return cur.lastrowid

    def set_status(self, mem_id: int, status: str):
        assert status in STATUSES
        self.conn.execute("UPDATE memories SET status=? WHERE id=?", (status, mem_id))
        self.conn.commit()

    def confirm_preference(self, mem_id: int, session: int):
        """Reset a preference's staleness clock (user re-confirmed it)."""
        self.conn.execute(
            "UPDATE memories SET last_confirmed_session=? WHERE id=?", (session, mem_id))
        self.conn.commit()

    # ------------------------------------------------------------------ reads

    def _query(self, where="", params=()) -> List[Memory]:
        sql = f"SELECT {', '.join(_COLUMNS)} FROM memories {where} ORDER BY id"
        return [_row_to_memory(r) for r in self.conn.execute(sql, params).fetchall()]

    def get(self, mem_id: int) -> Optional[Memory]:
        rows = self._query("WHERE id=?", (mem_id,))
        return rows[0] if rows else None

    def list_all(self) -> List[Memory]:
        return self._query()

    def list_active(self) -> List[Memory]:
        return self._query("WHERE status='active'")

    # ------------------------------------------------------------------ forgetting

    def apply_forgetting(self, current_session: int) -> dict:
        """Persist the forgetting policy for this session; return a change log.

        - Outcomes whose decayed weight falls below the floor are expired.
        - Stale preferences are reported (not expired) so the agent can prompt
          for re-confirmation.
        """
        expired, stale = [], []
        for m in self.list_active():
            if m.kind == "outcome":
                if m.effective_weight(current_session, self.half_life) < self.expire_floor:
                    self.set_status(m.id, "expired")
                    expired.append(m.id)
            elif m.kind == "preference" and m.stale(current_session, self.stale_after):
                stale.append(m.id)
        return {"expired_outcomes": expired, "stale_preferences": stale}
