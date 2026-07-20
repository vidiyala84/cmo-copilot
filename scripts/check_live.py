"""Live connectivity check for the configured LLM provider.

Run AFTER filling DASHSCOPE_API_KEY into .env: `python scripts/check_live.py`
Makes exactly ONE real model call, then a full single-scenario baseline run.
Costs a few tokens. Mock mode / tests never touch this.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root on path

from cmo.config import LLM_PROVIDER, MODELS, QWEN_API_KEY, QWEN_API_KEY_ENV  # noqa: E402


def main():
    print(f"provider   = {LLM_PROVIDER}")
    print(f"model      = {MODELS['orchestrator']}")
    print(f"cred check = {QWEN_API_KEY_ENV}")
    if not QWEN_API_KEY:
        print(f"\n✗ No credentials detected. Fill {QWEN_API_KEY_ENV} in .env, then re-run.")
        return 1

    from cmo.llm import default_live_llm
    print("\n[1/2] one-shot model call…")
    try:
        llm = default_live_llm()
        msg = llm.complete([
            {"role": "system", "content": "Reply with a single word."},
            {"role": "user", "content": "Say OK."}])
        print(f"    ✓ response: {(msg.content or '').strip()[:80]!r}")
        print(f"    ✓ tokens:   {llm.usage()}")
    except Exception as e:
        print(f"    ✗ call failed: {type(e).__name__}: {e}")
        print("    → check the DASHSCOPE_API_KEY, the base URL "
              "(dashscope-intl compatible-mode), and that the model ids in "
              "QWEN_*_MODEL match the Model Studio console.")
        return 2

    print("\n[2/2] one scenario through the live baseline agent…")
    from cmo.agents import QwenBaselineAgent
    from cmo.datagen import generate_base
    from cmo.scenarios import SCENARIOS
    from cmo.tools import ScenarioEnv
    from cmo.harness import score
    env = ScenarioEnv(generate_base(), SCENARIOS[0])
    decision = QwenBaselineAgent().decide(env)
    s, _ = score(decision, SCENARIOS[0]["expected"])
    print(f"    ✓ S01 decision: {decision.get('root_cause')} / {decision.get('action')}  "
          f"(score {s}, tools called: {len(env.tool_log)})")
    print("\n✓ Live provider is working. You can now run:  python harness.py --agent qwen")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
