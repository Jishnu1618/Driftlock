#!/usr/bin/env bash
# Starts what every DriftLock session needs, from the repository's own directory.
# DriftLock's user-facing surface is the Streamlit dashboard (app.py), so this
# launches it in the background and exits. Safe to re-run on a disk resume: an
# already running dashboard is left alone.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Logs live outside the repository so the working tree stays clean.
LOG_DIR="${HOME}/.alan/logs"
LOG_FILE="${LOG_DIR}/driftlock-start.log"
mkdir -p "$LOG_DIR"

PORT="${DRIFTLOCK_PORT:-8501}"
VENV_PY="$REPO_DIR/.venv/bin/python"

if [ ! -x "$VENV_PY" ]; then
  # The image build normally provides .venv; recreate it if it is missing.
  python3 -m venv .venv
  "$VENV_PY" -m pip install --disable-pip-version-check -r requirements.txt
fi

# Skip the launch when the dashboard already answers (disk resume).
if curl -fsS -o /dev/null --max-time 2 "http://127.0.0.1:${PORT}/_stcore/health"; then
  echo "DriftLock dashboard already running on port ${PORT}"
  exit 0
fi

# Plain start command, backgrounded, output to the log file.
nohup "$VENV_PY" -m streamlit run app.py \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --server.headless true \
  --browser.gatherUsageStats false \
  >>"$LOG_FILE" 2>&1 &

echo "DriftLock dashboard starting on port ${PORT} (log: $LOG_FILE)"