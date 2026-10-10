#!/usr/bin/env bash
# Jarvis setup for macOS. Run from anywhere:  bash scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ needed"'
[ -d .venv ] || "$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/jarvis init

cat <<'EOF'

Next:
  .venv/bin/jarvis secret set anthropic_api_key   # stored in the macOS Keychain
  .venv/bin/python -m pytest
  .venv/bin/jarvis chat
EOF
