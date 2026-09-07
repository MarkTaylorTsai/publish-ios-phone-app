from __future__ import annotations

import base64
import json
import os
import plistlib
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


ASC_BASE = "https://api.appstoreconnect.apple.com/v1"
OPENSSL_BIN = next(
    (candidate for candidate in (os.environ.get("OPENSSL_BIN", ""), "/opt/homebrew/bin/openssl", "/usr/local/bin/openssl", shutil.which("openssl") or "") if candidate and Path(candidate).is_file()),
    "openssl",
)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _der_ecdsa_to_raw(signature: bytes, size: int = 32) -> bytes:
    if not signature or signature[0] != 0x30:
        raise ValueError("invalid ECDSA DER signature")
    pos = 1
    length = signature[pos]
    pos += 1
    if length & 0x80:
        count = length & 0x7F
        length = int.from_bytes(signature[pos:pos + count], "big")
        pos += count
    if signature[pos] != 0x02:
        raise ValueError("invalid ECDSA r")
    pos += 1
    rlen = signature[pos]
    pos += 1
    r = signature[pos:pos + rlen]
    pos += rlen
    if signature[pos] != 0x02:
        raise ValueError("invalid ECDSA s")
    pos += 1
    slen = signature[pos]
    pos += 1
    s = signature[pos:pos + slen]
    r = r.lstrip(b"\0").rjust(size, b"\0")
    s = s.lstrip(b"\0").rjust(size, b"\0")
    if len(r) != size or len(s) != size:
        raise ValueError("unexpected ECDSA component size")
    return r + s


def make_jwt(key_id: str, issuer_id: str, private_key_path: str) -> str:
    now = int(time.time())
    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {"iss": issuer_id, "iat": now, "exp": now + 600, "aud": "appstoreconnect-v1"}
    signing_input = f"{_b64url(json.dumps(header,separators=(',',':')).encode())}.{_b64url(json.dumps(payload,separators=(',',':')).encode())}".encode()
    result = subprocess.run(
        [OPENSSL_BIN, "dgst", "-sha256", "-sign", private_key_path],
        input=signing_input,
        capture_output=True,
        check=True,
    )
    return signing_input.decode() + "." + _b64url(_der_ecdsa_to_raw(result.stdout))


def _request(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, dict]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        ASC_BASE + path,
        data=data,
        method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            return response.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        detail = raw.decode("utf-8", "replace")[:1200]
        raise RuntimeError(f"App Store Connect API {exc.code}: {detail}") from exc


def register_device(udid: str, name: str, env: dict[str, str]) -> dict:
    jwt = make_jwt(env["ASC_KEY_ID"], env["ASC_ISSUER_ID"], env["ASC_PRIVATE_KEY_PATH"])
    query = urllib.parse.urlencode({"filter[udid]": udid, "limit": 1})
    _, existing = _request("GET", f"/devices?{query}", jwt)
    if existing.get("data"):
        status = existing["data"][0].get("attributes", {}).get("status")
        if status and status != "ENABLED":
            raise RuntimeError(f"Apple device exists but is not enabled: {status}")
        return {"created": False, "device": existing["data"][0]}
    body = {"data": {"type": "devices", "attributes": {"name": name[:100], "platform": "IOS", "udid": udid}}}
    _, created = _request("POST", "/devices", jwt, body)
    return {"created": True, "device": created.get("data")}


def _validate_exported_ipa(ipa_path: Path, config: dict, expected_udid: str) -> None:
    with zipfile.ZipFile(ipa_path) as archive, tempfile.TemporaryDirectory(prefix="ios-provision-check-") as temp_dir:
        info_names = [name for name in archive.namelist() if name.startswith("Payload/") and name.endswith(".app/Info.plist") and name.count("/") == 2]
        provision_names = [name for name in archive.namelist() if name.startswith("Payload/") and name.endswith(".app/embedded.mobileprovision") and name.count("/") == 2]
        if len(info_names) != 1 or len(provision_names) != 1:
            raise RuntimeError("exported IPA has an invalid top-level app structure")
        info = plistlib.loads(archive.read(info_names[0]))
        if str(info.get("CFBundleIdentifier", "")) != str(config["bundle_id"]):
            raise RuntimeError("exported IPA bundle identifier does not match config")
        if str(info.get("CFBundleVersion", "")) != str(config["bundle_version"]):
            raise RuntimeError("exported IPA build number does not match config")
        provision_path = Path(temp_dir) / "embedded.mobileprovision"
        provision_path.write_bytes(archive.read(provision_names[0]))
        decoded = subprocess.run(
            ["security", "cms", "-D", "-i", str(provision_path)],
            capture_output=True,
            timeout=30,
        )
        if decoded.returncode != 0:
            raise RuntimeError("could not decode exported provisioning profile")
        profile = plistlib.loads(decoded.stdout)
        if expected_udid not in set(profile.get("ProvisionedDevices", [])):
            raise RuntimeError("new device is absent from exported Ad Hoc provisioning profile")
        if profile.get("ProvisionsAllDevices"):
            raise RuntimeError("export used an enterprise profile instead of Ad Hoc")


def export_command(config: dict, env: dict[str, str], export_path: str) -> list[str]:
    """Select export credentials explicitly; never switch identities on failure."""
    authentication = config.get("export_authentication", "api-key")
    if authentication not in {"api-key", "xcode-account"}:
        raise ValueError("export_authentication must be api-key or xcode-account")
    command = [
        "xcodebuild", "-exportArchive",
        "-archivePath", str(config["archive_path"]),
        "-exportPath", export_path,
        "-exportOptionsPlist", str(config["export_options_path"]),
        "-allowProvisioningUpdates",
    ]
    if authentication == "api-key":
        required = ("ASC_PRIVATE_KEY_PATH", "ASC_KEY_ID", "ASC_ISSUER_ID")
        if not all(env.get(key) for key in required):
            raise ValueError("api-key export requires all three ASC credential settings")
        command += [
            "-authenticationKeyPath", env["ASC_PRIVATE_KEY_PATH"],
            "-authenticationKeyID", env["ASC_KEY_ID"],
            "-authenticationKeyIssuerID", env["ASC_ISSUER_ID"],
        ]
    # xcode-account deliberately uses the signed-in Xcode account of the
    # service's macOS user. The ASC team key still handles device registration.
    return command


def export_ipa(config: dict, env: dict[str, str], output_path: Path, expected_udid: str) -> Path:
    archive = Path(config["archive_path"])
    options = Path(config["export_options_path"])
    if not archive.exists() or not options.exists():
        raise RuntimeError("缺少既有 Xcode archive 或 ExportOptions plist")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ios-adhoc-export-") as temp_dir:
        cmd = export_command(config, env, temp_dir)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
        if result.returncode != 0:
            tail = (result.stdout + "\n" + result.stderr)[-5000:]
            raise RuntimeError("xcodebuild 匯出失敗：" + tail)
        candidates = list(Path(temp_dir).glob("*.ipa"))
        if len(candidates) != 1:
            raise RuntimeError("xcodebuild 未產生唯一 IPA")
        _validate_exported_ipa(candidates[0], config, expected_udid)
        staging = output_path.with_suffix(".ipa.new")
        shutil.copy2(candidates[0], staging)
        os.replace(staging, output_path)
    return output_path


def configured(env: dict[str, str]) -> bool:
    required = ("ASC_KEY_ID", "ASC_ISSUER_ID", "ASC_PRIVATE_KEY_PATH")
    return all(env.get(k) for k in required) and Path(env["ASC_PRIVATE_KEY_PATH"]).exists()
