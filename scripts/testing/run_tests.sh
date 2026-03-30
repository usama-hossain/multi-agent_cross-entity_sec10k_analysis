#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found at $PYTHON_BIN"
  echo "Set PYTHON_BIN or create .venv first."
  exit 1
fi

echo "[tests] Running unit test suite..."
"$PYTHON_BIN" -m pytest tests/unit -v --tb=short

if [[ "${RUN_LIVE_BATCH_TESTS:-false}" =~ ^([Tt][Rr][Uu][Ee]|1|[Yy][Ee][Ss]|[Oo][Nn])$ ]]; then
  echo "[tests] Running optional live smoke tests..."
  "$PYTHON_BIN" -m pytest tests/integration -v --tb=short
else
  echo "[tests] Skipping live smoke tests (set RUN_LIVE_BATCH_TESTS=true to enable)."
fi

echo "[tests] Completed."
