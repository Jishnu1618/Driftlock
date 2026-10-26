#!/usr/bin/env bash
# Installs the DriftLock toolchain and dependencies into the environment image.
# Runs once per image build, from the repository's own directory.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# DriftLock requires Python >= 3.11; Ubuntu 24.04 ships 3.12 in the image.
python3 -m venv .venv

# Install the dependency set from requirements.txt, as the README documents
# (it includes streamlit for the dashboard). The repository has no lockfile, so
# this file is the source of truth and versions stay as the repository declares.
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt

# The package is used from the repository root: pytest sets pythonpath = ["."],
# the CLI is documented as `python -m driftlock.cli.main`, and the dashboard is
# `streamlit run app.py`. It is not pip-installed because pyproject.toml has no
# package discovery config, so building the project fails while a second
# top-level directory (fixtures/) exists.
.venv/bin/python -c "import driftlock; print('driftlock', driftlock.__version__)"

echo "DriftLock environment ready: $REPO_DIR/.venv"