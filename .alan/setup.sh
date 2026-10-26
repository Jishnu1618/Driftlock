#!/usr/bin/env bash
# Installs the DriftLock toolchain and dependencies into the environment image.
# Runs once per image build, from the repository's own directory.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# DriftLock requires Python >= 3.11; Ubuntu 24.04 ships 3.12 in the image.
python3 -m venv .venv

# Install the pinned dependency set from the repository's requirements file.
# No lockfile exists in the repository, so requirements.txt is the source of truth.
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt

# Install DriftLock itself in editable mode so `import driftlock` and the
# `driftlock` console script resolve from the checked-out sources.
.venv/bin/python -m pip install --disable-pip-version-check -e .

# Sanity check: the package must import cleanly in a fresh interpreter.
.venv/bin/python -c "import driftlock; print('driftlock', driftlock.__version__)"

echo "DriftLock environment ready: $REPO_DIR/.venv"
