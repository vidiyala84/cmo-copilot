"""H1-2 — memory retrieval under a tight context budget (Track 1).

Score = relevance x recency x outcome_weight.

  relevance  — cosine similarity of embeddings when an embedder is available;
               keyword-overlap fallback otherwise. Same `retrieve(...)`
               interface either way — the fallback is a drop-in, never a blocker.
  recency    — half-life decay on session age (preferences measure age from
               their last-confirmed session, so re-confirming refreshes them).
  weight     — the memory's effective (decayed) outcome weight.

Hard cap: the returned block is <= `token_cap` tokens (~4 chars/token). Memories
are added highest-score first; the lowest-scoring ones that don't fit are dropped.
"""
import math
import os
import re
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from tracks.track1.memory_store import Memory, MemoryStore

RECENCY_HALF_LIFE = int(os.environ.get("MEM_RECENCY_HALF_LIFE", "3"))
DEFAULT_TOKEN_CAP = 1500
_WORD = re.compile(r"[a-z0-9]+")


def _toklen(text: str) -> int:
    return max(1, len(text) // 4)  # ~4 chars/token


def _tokens(text: str):
    return set(_WORD.findall((text or "").lower()))


def lexical_relevance(query: str, text: str) -> float:
    """Overlap coefficient of query terms present in the memory text, [0,1]."""
    q, t = _tokens(query), _tokens(text)
    if not q or not t:
        return 0.0
    return len(q & t) / len(q)


def cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def recency(reference_session: int, current_session: int,
            half_life: int = RECENCY_HALF_LIFE) -> float:
    age = max(0, current_session - reference_session)
    if half_life <= 0:
        return 1.0
    return 0.5 ** (age / half_life)


@dataclass
class Scored:
    memory: Memory
    score: float
    relevance: float
    recency: float
    weight: float


@dataclass
class RetrievalResult:
    scored: List[Scored] = field(default_factory=list)   # included, score desc
    dropped: List[Scored] = field(default_factory=list)  # cut by the token cap
    block: str = ""
    used_tokens: int = 0
    used_embeddings: bool = False

    @property
    def memories(self) -> List[Memory]:
        return [s.memory for s in self.scored]


class Retriever:
    def __init__(self, store: MemoryStore, embedder: Optional[Callable] = None,
                 recency_half_life: int = RECENCY_HALF_LIFE,
                 token_cap: int = DEFAULT_TOKEN_CAP):
        self.store = store
        self.embedder = embedder
        self.recency_half_life = recency_half_life
        self.token_cap = token_cap

    # ---------------------------------------------------------------- relevance

    def _relevances(self, query: str, texts: List[str]):
        """Return (relevances, used_embeddings). Falls back to lexical on any error."""
        if self.embedder is not None:
            try:
                vecs = self.embedder([query] + texts)
                qv, mvs = vecs[0], vecs[1:]
                rels = [max(0.0, cosine(qv, mv)) for mv in mvs]
                return rels, True
            except Exception:  # noqa: BLE001 — embedding failure must degrade, not crash
                pass
        return [lexical_relevance(query, t) for t in texts], False

    # ---------------------------------------------------------------- retrieval

    def _reference_session(self, m: Memory) -> int:
        return m.last_confirmed_session if m.kind == "preference" else m.session_created

    def retrieve(self, query: str, current_session: int,
                 token_cap: Optional[int] = None) -> RetrievalResult:
        cap = self.token_cap if token_cap is None else token_cap
        memories = self.store.list_active()
        if not memories:
            return RetrievalResult()

        rels, used_emb = self._relevances(query, [m.text for m in memories])
        scored = []
        for m, rel in zip(memories, rels):
            rec = recency(self._reference_session(m), current_session, self.recency_half_life)
            w = m.effective_weight(current_session)
            scored.append(Scored(m, rel * rec * w, rel, rec, w))
        scored.sort(key=lambda s: s.score, reverse=True)

        # Include a highest-score-first prefix; stop at the first line that
        # doesn't fit so every kept memory outscores every dropped one.
        included, dropped, used, lines = [], [], 0, []
        overflowed = False
        for s in scored:
            line = self._format(s, current_session)
            cost = _toklen(line)
            if not overflowed and used + cost <= cap:
                included.append(s)
                lines.append(line)
                used += cost
            else:
                overflowed = True
                dropped.append(s)
        return RetrievalResult(scored=included, dropped=dropped,
                               block="\n".join(lines), used_tokens=used,
                               used_embeddings=used_emb)

    def _format(self, s: Scored, current_session: int) -> str:
        m = s.memory
        tags = [m.kind]
        if m.campaign_id:
            tags.append(m.campaign_id)
        if m.stale(current_session):
            tags.append("stale?")
        return f"- [{', '.join(tags)}] {m.text} (conf={m.confidence:.2f}, w={s.weight:.2f})"


# ----------------------------------------------------------------- embedder

class ModelStudioEmbedder:
    """OpenAI-compatible embeddings on Model Studio (text-embedding-v3). Any
    failure -> retriever silently uses the lexical fallback."""

    def __init__(self, client=None, model=None):
        self.model = model or os.environ.get("QWEN_EMBED_MODEL", "text-embedding-v3")
        self._client = client

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            from cmo.config import QWEN_API_KEY, QWEN_BASE_URL
            self._client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        return self._client

    def __call__(self, texts: List[str]) -> List[List[float]]:
        resp = self._get_client().embeddings.create(model=self.model, input=texts)
        return [d.embedding for d in resp.data]


def get_embedder(mock: bool):
    """Mock mode -> None (lexical). Live -> Model Studio embedder when a key is
    present; any failure falls back to lexical inside the retriever."""
    if mock:
        return None
    from cmo.config import QWEN_API_KEY
    return ModelStudioEmbedder() if QWEN_API_KEY else None
