#!/usr/bin/env python3
"""Read-only App Store Connect credential preflight for the installer workflow."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
CHECKS = {
    "apps": "/apps?limit=1",
    "devices": "/devices?limit=1",
    "bundleIds": "/bundleIds?limit=1",
    "profiles": "/profiles?limit=1",
}


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def der_ecdsa_to_raw(signature: bytes, size: int = 32) -> bytes:
    if not signature or signature[0] != 0x30:
        raise ValueError("invalid ECDSA DER signature")
    pos = 1
    length = signature[pos]
    pos += 1
    if length & 0x80:
        count = length & 0x7F
        pos += count
    if signature[pos] != 0x02:
        raise ValueError("invalid ECDSA r")
    pos += 1
    rlen = signature[pos]
    pos += 1
    r = signature[pos : pos + rlen]
    pos += rlen
    if signature[pos] != 0x02:
        raise ValueError("invalid ECDSA s")
    pos += 1
    slen = signature[pos]
    pos += 1
    s = signature[pos : pos + slen]
    r = r.lstrip(b"\0").rjust(size, b"\0")
    s = s.lstrip(b"\0").rjust(size, b"\0")
    if len(r) != size or len(s) != size:
        raise ValueError("unexpected ECDSA component size")
    return r + s


def make_jwt(key_id: str, issuer_id: str, private_key_path: Path) -> str:
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {"iss": issuer_id, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}
    signing_input = (
        f"{b64url(json.dumps(header, separators=(',', ':')).encode())}."
        f"{b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    ).encode()
    openssl = next(
        (
            candidate
            for candidate in (
                os.environ.get("OPENSSL_BIN", ""),
                "/opt/homebrew/bin/openssl",
                "/usr/local/bin/openssl",
                shutil.which("openssl") or "",
            )
            if candidate and Path(candidate).is_file()
        ),
        "openssl",
    )
    result = subprocess.run(
        [openssl, "dgst", "-sha256", "-sign", str(private_key_path)],
        input=signing_input,
        capture_output=True,
        check=True,
    )
    return signing_input.decode() + "." + b64url(der_ecdsa_to_raw(result.stdout))


def check(path: str, token: str) -> tuple[int, int | None]:
    request = urllib.request.Request(
        ASC_BASE + path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.load(response)
            data = body.get("data")
            return response.status, len(data) if isinstance(data, list) else None
    except urllib.error.HTTPError as error:
        error.read()
        return error.code, None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify a team App Store Connect API key without mutating Apple resources."
    )
    parser.add_argument("--env-file", type=Path, required=True)
    args = parser.parse_args()

    if not args.env_file.is_file():
        parser.error("--env-file must be an existing file")
    values = parse_env(args.env_file)
    missing = [
        key
        for key in ("ASC_ISSUER_ID", "ASC_KEY_ID", "ASC_PRIVATE_KEY_PATH")
        if not values.get(key)
    ]
    if missing:
        print(json.dumps({"ok": False, "missing": missing}, indent=2))
        return 2

    private_key = Path(values["ASC_PRIVATE_KEY_PATH"]).expanduser()
    if not private_key.is_file():
        print(json.dumps({"ok": False, "privateKeyReadable": False}, indent=2))
        return 2

    token = make_jwt(values["ASC_KEY_ID"], values["ASC_ISSUER_ID"], private_key)
    results: dict[str, dict[str, int | None]] = {}
    for name, path in CHECKS.items():
        status, returned = check(path, token)
        results[name] = {"httpStatus": status, "returnedItems": returned}
    ok = all(result["httpStatus"] == 200 for result in results.values())
    report = {
        "ok": ok,
        "credentialTypeRequired": "team",
        "readOnly": True,
        "checks": results,
        "secretsPrinted": False,
    }
    print(json.dumps(report, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
