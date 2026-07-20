#!/usr/bin/env bash
# Launch the showcase UI: FastAPI backend (:8000) + Next.js frontend (:3000).
# Usage: bash run_ui.sh   (Ctrl-C stops both)
set -euo pipefail
cd "$(dirname "$0")"

echo "▶ Installing backend deps (fastapi, uvicorn)…"
python3 -m pip install -q -r api/requirements.txt

if [ ! -d web/node_modules ]; then
  echo "▶ Installing frontend deps (first run)…"
  (cd web && npm install)
fi

echo "▶ Starting FastAPI on http://localhost:8000 …"
uvicorn api.main:app --port 8000 >/tmp/cmo-copilot_api.log 2>&1 &
API_PID=$!

echo "▶ Starting Next.js on http://localhost:3000 …"
(cd web && npm run dev) &
WEB_PID=$!

cleanup() { echo; echo "stopping…"; kill "$API_PID" "$WEB_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo ""
echo "  UI:   http://localhost:3000"
echo "  API:  http://localhost:8000/api/health   (logs: /tmp/cmo-copilot_api.log)"
echo ""
wait
