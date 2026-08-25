#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
cd "$ROOT"
[[ -x .venv/bin/python ]] || "$ROOT/scripts/setup.sh"
exec .venv/bin/python server.py
