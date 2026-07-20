"""H1-2 — retriever: token cap respected, ordering correct, fallback == interface."""
import pytest

from tracks.track1.memory_store import MemoryStore
from tracks.track1.retriever import (RetrievalResult, Retriever, cosine, lexical_relevance,
                              recency)


def _store():
    return MemoryStore(db_path=":memory:", half_life=3, stale_after=4)


# ------------------------------------------------------------------ primitives

def test_lexical_relevance_overlap():
    assert lexical_relevance("brand campaign floor", "never cut the brand campaign") == pytest.approx(2 / 3)
    assert lexical_relevance("", "anything") == 0.0
    assert lexical_relevance("nomatch here", "totally different words") == 0.0


def test_cosine_basic():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0


def test_recency_decay():
    assert recency(5, 5, 3) == 1.0
    assert recency(2, 5, 3) == pytest.approx(0.5)


# ------------------------------------------------------------------ ordering

def test_relevance_ordering():
    s = _store()
    s.add("preference", "never cut brand campaign C2 below floor", session=1, campaign_id="G2")
    s.add("outcome", "retargeting saturated last quarter", session=1, campaign_id="G3",
          topic="sat", polarity=-1)
    r = Retriever(s)
    res = r.retrieve("brand campaign floor", current_session=1)
    assert not res.used_embeddings
    assert "brand" in res.scored[0].memory.text            # most relevant first
    assert res.scored[0].score >= res.scored[-1].score


def test_recency_and_weight_break_ties():
    s = _store()
    old = s.add("outcome", "shift to C5 worked well", session=1, campaign_id="G5",
                topic="a", polarity=1)
    new = s.add("outcome", "shift to C5 worked well", session=5, campaign_id="G5",
                topic="b", polarity=1)
    r = Retriever(s)
    res = r.retrieve("shift to C5 worked well", current_session=5)
    # identical text/relevance -> the more recent, less-decayed one ranks first
    assert res.scored[0].memory.id == new
    assert res.scored[0].score > res.scored[1].score


def test_demoted_and_expired_excluded():
    s = _store()
    keep = s.add("preference", "conservative shifts only", session=1)
    drop = s.add("outcome", "conservative shifts only", session=1, campaign_id="G1",
                 topic="x", polarity=1)
    s.set_status(drop, "demoted")
    r = Retriever(s)
    res = r.retrieve("conservative shifts", current_session=1)
    ids = [sc.memory.id for sc in res.scored]
    assert keep in ids and drop not in ids


# ------------------------------------------------------------------ token cap

def test_token_cap_respected_and_drops_lowest():
    s = _store()
    # 20 memories, each formatted line ~30 tokens; a 90-token cap admits ~3.
    for i in range(20):
        rel = "brand floor" if i == 0 else f"unrelated topic number {i}"
        s.add("episode", f"{rel} " + ("padding words " * 6), session=1)
    r = Retriever(s)
    res = r.retrieve("brand floor", current_session=1, token_cap=90)
    assert res.used_tokens <= 90
    assert len(res.dropped) > 0
    # the on-topic memory must survive; something got dropped
    assert any("brand floor" in sc.memory.text for sc in res.scored)
    # every dropped item scores <= every kept item (lowest dropped first)
    if res.scored and res.dropped:
        assert min(sc.score for sc in res.scored) >= max(sc.score for sc in res.dropped)


def test_empty_store_returns_empty_result():
    r = Retriever(_store())
    res = r.retrieve("anything", current_session=1)
    assert isinstance(res, RetrievalResult)
    assert res.scored == [] and res.block == ""


# ------------------------------------------------------------------ fallback == interface

def test_embedder_path_same_interface_and_falls_back():
    s = _store()
    s.add("preference", "never cut brand", session=1, campaign_id="G2")
    s.add("outcome", "retargeting worked", session=1, campaign_id="G3", topic="a", polarity=1)

    # a working fake embedder: identical shape of result to the lexical path
    def fake_embed(texts):
        # crude: vector = [count of 'brand', count of 'retargeting']
        return [[t.lower().count("brand"), t.lower().count("retargeting")] for t in texts]

    emb = Retriever(s, embedder=fake_embed).retrieve("brand", current_session=1)
    lex = Retriever(s, embedder=None).retrieve("brand", current_session=1)
    assert emb.used_embeddings and not lex.used_embeddings
    assert type(emb) is type(lex)
    assert emb.scored[0].memory.text == lex.scored[0].memory.text  # same top pick

    # a broken embedder must transparently fall back to lexical
    def boom(texts):
        raise RuntimeError("embedding service down")

    fb = Retriever(s, embedder=boom).retrieve("brand", current_session=1)
    assert not fb.used_embeddings
    assert fb.scored[0].memory.text == lex.scored[0].memory.text
