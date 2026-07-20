"""H0-2 — shared LLM client: mock behaviour, tool loop, token accounting,
retry, budget guard, and the QwenLLM path exercised through a fake client."""
import json

import pytest

from cmo import harness
from cmo.datagen import generate_base
from cmo.scenarios import SCENARIOS
from cmo.tools import ScenarioEnv
from cmo.llm import (BudgetExceeded, Message, MockLLM, QwenLLM, ToolCall,
                 estimate_tokens, get_llm, over_budget_decision, tool_loop)
from cmo.tools import OPENAI_TOOL_SPECS


def _env():
    return ScenarioEnv(generate_base(), SCENARIOS[0])


# ------------------------------------------------------------------ factory

def test_get_llm_factory():
    assert isinstance(get_llm(mock=True), MockLLM)


def test_qwen_without_key_fails_loudly(monkeypatch):
    # No injected client + no key -> constructing QwenLLM must fail loudly.
    monkeypatch.setattr("cmo.llm.QWEN_API_KEY", "")
    with pytest.raises(RuntimeError):
        QwenLLM(client=None)


# ------------------------------------------------------------------ MockLLM

def test_mockllm_counts_tokens():
    llm = MockLLM(handler=lambda m, t, md: Message(content="hello world"))
    llm.complete([{"role": "user", "content": "hi there friend"}])
    assert llm.total_tokens > 0
    assert llm.n_calls == 1
    assert llm.prompt_tokens > 0 and llm.completion_tokens > 0


def test_mockllm_reset():
    llm = MockLLM(handler=lambda m, t, md: Message(content="x"))
    llm.complete([{"role": "user", "content": "abc"}])
    llm.reset()
    assert llm.total_tokens == 0 and llm.n_calls == 0


def test_estimate_tokens_monotonic():
    assert estimate_tokens("a" * 40) > estimate_tokens("a" * 4)
    assert estimate_tokens("") == 1


# ------------------------------------------------------------------ budget guard

def test_budget_guard_raises():
    llm = MockLLM(handler=lambda m, t, md: Message(content="x" * 400), budget=10)
    with pytest.raises(BudgetExceeded) as ei:
        llm.complete([{"role": "user", "content": "y" * 400}])
    assert ei.value.cap == 10
    assert ei.value.used > 10


def test_over_budget_decision_shape():
    d = over_budget_decision(100, 50)
    assert d["status"] == "over_budget"
    assert d["action"] == "no_action"


# ------------------------------------------------------------------ tool loop

def test_tool_loop_dispatches_then_answers():
    """Handler calls one tool on the first turn, then returns a final JSON answer."""
    calls = {"n": 0}

    def handler(messages, tools, model):
        calls["n"] += 1
        if calls["n"] == 1:
            return Message(tool_calls=[ToolCall(id="c1", name="get_campaign_metrics",
                                                arguments=json.dumps({"group_id": "G1"}))])
        return Message(content=json.dumps({"root_cause": "creative_fatigue",
                                           "action": "no_action"}))

    env = _env()
    llm = MockLLM(handler=handler)
    content, msg = tool_loop(llm, env, [{"role": "user", "content": "go"}])
    assert json.loads(content)["root_cause"] == "creative_fatigue"
    assert [e["tool"] for e in env.tool_log] == ["get_campaign_metrics"]
    assert llm.n_calls == 2


def test_tool_loop_bounded_by_max_calls():
    """A handler that always calls a tool must still terminate and answer."""
    def handler(messages, tools, model):
        if tools is None:  # forced final turn
            return Message(content="{}")
        return Message(tool_calls=[ToolCall(id="c", name="get_benchmarks", arguments="{}")])

    env = _env()
    llm = MockLLM(handler=handler)
    content, _ = tool_loop(llm, env, [{"role": "user", "content": "go"}], max_tool_calls=3)
    assert content == "{}"
    assert len(env.tool_log) == 3  # exactly max_tool_calls tool dispatches


# ------------------------------------------------------------------ QwenLLM (fake client)

class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.type = "function"
        self.function = type("F", (), {"name": name, "arguments": arguments})()


class _FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c


class _FakeResp:
    def __init__(self, message, usage):
        self.choices = [type("C", (), {"message": message})()]
        self.usage = usage


class _FakeCompletions:
    def __init__(self, script):
        self._script = list(script)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeClient:
    def __init__(self, script):
        self.chat = type("Chat", (), {"completions": _FakeCompletions(script)})()


def test_qwenllm_counts_usage_and_parses_tools():
    resp = _FakeResp(
        _FakeMessage(tool_calls=[_FakeToolCall("t1", "get_benchmarks", "{}")]),
        _FakeUsage(120, 30))
    llm = QwenLLM(client=_FakeClient([resp]))
    msg = llm.complete([{"role": "user", "content": "hi"}], tools=[])
    assert llm.total_tokens == 150
    assert msg.tool_calls[0].name == "get_benchmarks"


def test_qwenllm_retries_then_succeeds():
    good = _FakeResp(_FakeMessage(content="ok"), _FakeUsage(1, 1))
    client = _FakeClient([RuntimeError("boom"), RuntimeError("boom2"), good])
    slept = []
    llm = QwenLLM(client=client, retries=3, backoff_base=0.01,
                  sleep_fn=lambda s: slept.append(s))
    msg = llm.complete([{"role": "user", "content": "hi"}])
    assert msg.content == "ok"
    assert len(slept) == 2  # two backoffs before the third succeeds


def test_qwenllm_gives_up_after_retries():
    client = _FakeClient([RuntimeError("a"), RuntimeError("b"), RuntimeError("c")])
    llm = QwenLLM(client=client, retries=3, backoff_base=0.0, sleep_fn=lambda s: None)
    with pytest.raises(RuntimeError):
        llm.complete([{"role": "user", "content": "hi"}])


# ------------------------------------------------------------------ baseline refactor

def test_qwen_baseline_agent_via_injected_llm():
    """QwenBaselineAgent behaviour is unchanged; here driven by a MockLLM."""
    from cmo.agents import QwenBaselineAgent

    def handler(messages, tools, model):
        return Message(content=json.dumps({
            "root_cause": "creative_fatigue", "action": "shift_budget",
            "source_campaign": "G1", "target_campaign": "G5", "shift_pct": 15,
            "rationale": "canned"}))

    agent = QwenBaselineAgent(llm=MockLLM(handler=handler))
    decision = agent.decide(_env())
    assert decision["root_cause"] == "creative_fatigue"
    assert decision["action"] == "shift_budget"


def test_baseline_agent_budget_abort():
    from cmo.agents import QwenBaselineAgent

    def handler(messages, tools, model):
        return Message(content="x" * 1000)

    agent = QwenBaselineAgent(llm=MockLLM(handler=handler, budget=5))
    decision = agent.decide(_env())
    assert decision["status"] == "over_budget"


def test_mock_canary_holds(mock_baseline_total):
    from cmo.agents import MockHeuristicAgent
    total = sum(r["score"] for r in harness.run(MockHeuristicAgent()))
    assert round(total, 1) == mock_baseline_total
