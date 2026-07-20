"""Shared LLM client for every track (H0-2).

Two implementations behind one interface:

  QwenLLM  — OpenAI-compatible chat + tool-calling, real token accounting from
             API usage fields, retry with exponential backoff, budget guard.
  MockLLM  — same interface, deterministic canned behaviour via an injected
             handler, estimated token accounting so budgets/metrics still work
             offline with no API key.

`get_llm(mock=...)` is the factory. `tool_loop(...)` drives multi-turn tool
calling identically for both, appending every tool result to the message list
and letting the caller read `env.tool_log` afterwards.

Budget guard: token usage accumulates per LLM instance; when it crosses
`MAX_TOKENS_PER_RUN` the next accounting call raises `BudgetExceeded`. Agents
catch it and return `over_budget_decision(...)` — the run aborts that scenario
cleanly, it never hangs.
"""
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from cmo.config import (LLM_PROVIDER, MODELS, QWEN_API_KEY, QWEN_API_KEY_ENV,
                    QWEN_BASE_URL)
from cmo.tools import OPENAI_TOOL_SPECS


def _max_tokens_per_run() -> int:
    return int(os.environ.get("MAX_TOKENS_PER_RUN", "60000"))


# ----------------------------------------------------------------- data types

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str = "{}"  # JSON string, matching the OpenAI wire format


@dataclass
class Message:
    content: Optional[str] = None
    tool_calls: List[ToolCall] = field(default_factory=list)


class BudgetExceeded(RuntimeError):
    def __init__(self, used: int, cap: int):
        self.used, self.cap = used, cap
        super().__init__(f"token budget exceeded: used {used} > cap {cap}")


def over_budget_decision(used: int, cap: int) -> dict:
    """Canonical decision emitted when a run trips the budget guard."""
    return {
        "root_cause": "noise", "action": "no_action",
        "source_campaign": None, "target_campaign": None, "shift_pct": None,
        "rationale": f"Aborted: token budget exceeded ({used} > {cap}).",
        "status": "over_budget",
    }


# ----------------------------------------------------------------- base client

class BaseLLM:
    def __init__(self, budget: Optional[int] = None):
        self.max_tokens = _max_tokens_per_run() if budget is None else budget
        self.reset()

    def reset(self):
        """Zero the per-run counters. Call at the start of every scenario."""
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.n_calls = 0

    def usage(self) -> dict:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "n_calls": self.n_calls,
        }

    def _account(self, prompt_toks: int, completion_toks: int):
        self.prompt_tokens += prompt_toks
        self.completion_tokens += completion_toks
        self.total_tokens += prompt_toks + completion_toks
        self.n_calls += 1
        if self.total_tokens > self.max_tokens:
            raise BudgetExceeded(self.total_tokens, self.max_tokens)

    def complete(self, messages, tools=None, model=None) -> Message:
        raise NotImplementedError


# ----------------------------------------------------------------- Qwen client

class QwenLLM(BaseLLM):
    def __init__(self, client=None, model: Optional[str] = None, retries: int = 3,
                 backoff_base: float = 0.5, sleep_fn: Callable[[float], None] = time.sleep,
                 budget: Optional[int] = None):
        super().__init__(budget)
        if client is None:
            from openai import OpenAI  # lazy: mock mode needs no openai import path
            if not QWEN_API_KEY:
                raise RuntimeError(
                    f"Set {QWEN_API_KEY_ENV} to use QwenLLM on provider '{LLM_PROVIDER}' "
                    f"(or run in --mock mode).")
            client = OpenAI(api_key=QWEN_API_KEY, base_url=QWEN_BASE_URL)
        self.client = client
        self.model = model or MODELS["orchestrator"]
        self.retries = retries
        self.backoff_base = backoff_base
        self.sleep_fn = sleep_fn

    def complete(self, messages, tools=None, model=None) -> Message:
        kwargs = {"model": model or self.model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        last_err = None
        for attempt in range(self.retries):
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except Exception as e:  # noqa: BLE001 — retry any transient API failure
                last_err = e
                if attempt == self.retries - 1:
                    raise
                self.sleep_fn(self.backoff_base * (2 ** attempt))
        else:  # pragma: no cover — loop always breaks or raises
            raise last_err

        usage = getattr(resp, "usage", None)
        if usage is not None:
            self._account(getattr(usage, "prompt_tokens", 0) or 0,
                          getattr(usage, "completion_tokens", 0) or 0)
        m = resp.choices[0].message
        tcs = [ToolCall(tc.id, tc.function.name, tc.function.arguments or "{}")
               for tc in (m.tool_calls or [])]
        return Message(content=m.content, tool_calls=tcs)


# ----------------------------------------------------------------- Mock client

def estimate_tokens(text: str) -> int:
    """~4 chars/token, matching the retriever's context-budget approximation."""
    return max(1, len(text or "") // 4)


def _default_handler(messages, tools, model) -> Message:
    return Message(content=json.dumps({
        "root_cause": "noise", "action": "no_action", "source_campaign": None,
        "target_campaign": None, "shift_pct": None, "rationale": "mock default"}))


class MockLLM(BaseLLM):
    """Deterministic, offline. `handler(messages, tools, model) -> Message`."""

    def __init__(self, handler: Optional[Callable] = None, budget: Optional[int] = None):
        super().__init__(budget)
        self.handler = handler or _default_handler

    def complete(self, messages, tools=None, model=None) -> Message:
        prompt_toks = sum(estimate_tokens(str(m.get("content") or "")) for m in messages)
        msg = self.handler(messages, tools, model)
        completion_toks = estimate_tokens(msg.content or "") + sum(
            estimate_tokens(tc.arguments) for tc in msg.tool_calls)
        self._account(prompt_toks, completion_toks)
        return msg


# ----------------------------------------------------------------- factory + loop

def default_live_llm(**kwargs) -> BaseLLM:
    """The live client — Qwen on Model Studio via the OpenAI-compatible endpoint."""
    return QwenLLM(**kwargs)


def get_llm(mock: bool, **kwargs) -> BaseLLM:
    return MockLLM(**kwargs) if mock else default_live_llm(**kwargs)


def _assistant_msg(msg: Message) -> dict:
    return {
        "role": "assistant",
        "content": msg.content or "",
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name, "arguments": tc.arguments}}
            for tc in msg.tool_calls
        ],
    }


def tool_loop(llm: BaseLLM, env, messages, tools=OPENAI_TOOL_SPECS,
              model=None, max_tool_calls: int = 8):
    """Run a tool-calling conversation to completion.

    Returns (final_content, final_message). Every tool call is dispatched
    through `env.call` (which records the audit trail). Raises BudgetExceeded
    if the budget guard trips — callers convert that to over_budget_decision.
    """
    for _ in range(max_tool_calls):
        msg = llm.complete(messages, tools=tools, model=model)
        if not msg.tool_calls:
            return msg.content, msg
        messages.append(_assistant_msg(msg))
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            result = env.call(tc.name, args)
            messages.append({"role": "tool", "tool_call_id": tc.id,
                             "content": json.dumps(result)})
    # tool budget exhausted — one last completion without tools to force an answer
    final = llm.complete(messages, tools=None, model=model)
    return final.content, final
