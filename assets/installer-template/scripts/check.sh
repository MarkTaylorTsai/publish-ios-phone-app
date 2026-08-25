#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
cd "$ROOT"
[[ -x .venv/bin/python ]] || "$ROOT/scripts/setup.sh"
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile server.py provisioning.py templates.py
python3 -m json.tool config.json >/dev/null
"$ROOT/.venv/bin/python" scripts/verify-config.py
[[ -f .env && "$(stat -f '%Lp' .env)" == "600" ]]
[[ -d "$(python3 -c 'import json; print(json.load(open("config.json"))["archive_path"])')" ]]
[[ -f "$(python3 -c 'import json; print(json.load(open("config.json"))["export_options_path"])')" ]]
echo "checks passed"
