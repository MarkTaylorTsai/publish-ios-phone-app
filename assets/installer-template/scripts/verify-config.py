#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
config = json.loads((ROOT / "config.json").read_text("utf-8"))
env = dict(os.environ)
for raw in (ROOT / ".env").read_text("utf-8").splitlines():
    if raw and not raw.lstrip().startswith("#") and "=" in raw:
        key, value = raw.split("=", 1)
        env.setdefault(key.strip(), value.strip().strip('"').strip("'"))

errors: list[str] = []
origin = urllib.parse.urlparse(str(config.get("base_url", "")))
if origin.scheme != "https" or not origin.hostname:
    errors.append("base_url must be a valid HTTPS origin")
for key in ("archive_path", "initial_ipa_path", "export_options_path", "icon_57_path", "icon_512_path"):
    if not Path(str(config.get(key, ""))).exists():
        errors.append(f"{key} does not exist")
if not str(config.get("profile_sign_identity", "")).strip():
    signing_paths = ("profile_sign_certificate_path", "profile_sign_chain_path", "profile_sign_private_key_path")
    if not all(str(config.get(key, "")).strip() and Path(str(config[key])).is_file() for key in signing_paths):
        errors.append("configure profile_sign_identity or all three profile signing certificate paths")
for key in ("DATA_ENCRYPTION_KEY", "INSTALL_PORTAL_TOKEN", "ASC_ISSUER_ID", "ASC_KEY_ID", "ASC_PRIVATE_KEY_PATH"):
    if not env.get(key):
        errors.append(f"{key} is empty")
if env.get("ASC_PRIVATE_KEY_PATH") and not Path(env["ASC_PRIVATE_KEY_PATH"]).expanduser().is_file():
    errors.append("ASC_PRIVATE_KEY_PATH does not exist")
if errors:
    raise SystemExit("configuration errors:\n- " + "\n- ".join(errors))
print("configuration verified")
