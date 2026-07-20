#!/usr/bin/env bash
# H4-2 — every mock-mode command in DEMO.md must run cleanly from a clean checkout.
# Usage: bash tests/run_demo_commands.sh
set -euo pipefail

cd "$(dirname "$0")/.."
export DASHSCOPE_API_KEY=""          # prove nothing needs a key
export AWS_BEARER_TOKEN_BEDROCK=""

run() {
  echo "──▶ $*"
  "$@" >/dev/null
  echo "   ok"
}

echo "== setup =="
run python datagen.py

echo "== canary =="
# harness must print exactly 5.8
OUT="$(python harness.py --agent mock | grep 'Total:')"
echo "   $OUT"
echo "$OUT" | grep -q "5.8 / 10" || { echo "CANARY FAILED"; exit 1; }

echo "== Demo 1: Track 1 memory =="
run python -m track1.session_runner --sessions 5 --agent mock

echo "== Demo 2: Track 3 society =="
run python harness.py --agent society --mock

echo "== Demo 3: Track 4 autopilot =="
run python -m track4.autopilot --all --mock --auto-approve
run python -m track4.autopilot --scenario S01 --mock --auto-approve --inject-fault api500

echo "== Demo 4: bench =="
run python bench.py --mock

echo "== artifacts present =="
for f in runs/track1_curve.png runs/comparison.md runs/comparison.png \
         runs/bench.json runs/transcripts/S07.json runs/track4_report_S01.md \
         runs/approvals.jsonl; do
  test -f "$f" && echo "   ✓ $f" || { echo "   ✗ missing $f"; exit 1; }
done

echo ""
echo "ALL DEMO COMMANDS PASSED"
