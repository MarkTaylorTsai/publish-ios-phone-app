#!/bin/zsh
set -euo pipefail
ROOT="${0:A:h:h}"
cd "$ROOT"

python3 -m venv .venv
.venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt
mkdir -p data/profiles logs runtime

if [[ ! -f .env ]]; then
  echo "missing .env; generate the portal with scaffold_installer.py" >&2
  exit 1
fi
chmod 600 .env

security find-certificate -a -p /System/Library/Keychains/SystemRootCertificates.keychain > data/system-roots.pem
chmod 600 data/system-roots.pem

.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m py_compile server.py provisioning.py templates.py
python3 -m json.tool config.json >/dev/null
.venv/bin/python scripts/verify-config.py
echo "setup and checks complete"
