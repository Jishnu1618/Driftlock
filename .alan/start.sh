#!/usr/bin/env bash
# Starts what every DriftLock session needs, from the repository's own directory.
# DriftLock is a library plus CLI with no external services (no database, queue,
# or web server), so there is no long-running daemon to launch. This script
# makes sure the virtual environment is present and usable, and records a
# readiness line for the session. It is safe to re-run on a disk resume.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Logs live outside the repository so the working tree stays clean.
LOG_DIR="${HOME}/.alan/logs"
LOG_FILE="$LOG_DIR/driftlock-start.log"
mkdir -p "$LOG_DIR"

if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
  # The image build normally provides .venv; recreate it if it is missing.
  python3 -m venv .venv
  .venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
fi

{
  echo "--- driftlock session start $(date -Is) ---"
  "$REPO_DIR/.venv/bin/python" -c "import driftlock; print('driftlock', driftlock.__version__)"
  "$REPO_DIR/.venv/bin/python" -m driftlock.cli.main --help >/dev/null && echo "cli: ok"
  echo "interpreter: $REPO_DIR/.venv/bin/python"
  echo "repo: $REPO_DIR"
} >>"$LOG_FILE" 2>&1

echo "DriftLock ready. Activate with: source $REPO_DIR/.venv/bin/activate"