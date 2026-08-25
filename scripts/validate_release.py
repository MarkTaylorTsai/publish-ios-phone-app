#!/usr/bin/env python3
"""Validate an Ad Hoc IPA, OTA manifest, signing, and optional public download."""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path


def load_bytes(location: str) -> bytes:
    if location.startswith(("https://", "http://")):
        with urllib.request.urlopen(location, timeout=60) as response:
            return response.read()
    return Path(location).expanduser().read_bytes()


def decode_provision(path: Path) -> dict:
    commands = []
    if shutil.which("security"):
        commands.append(["security", "cms", "-D", "-i", str(path)])
    if shutil.which("openssl"):
        commands.append(["openssl", "cms", "-verify", "-noverify", "-inform", "DER", "-in", str(path)])
    for command in commands:
        result = subprocess.run(command, capture_output=True, timeout=30)
        if result.returncode == 0:
            return plistlib.loads(result.stdout)
    raise RuntimeError("could not decode embedded.mobileprovision")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipa", required=True, type=Path)
    parser.add_argument("--manifest", required=True, help="local plist path or HTTPS URL")
    parser.add_argument("--expected-bundle-id", required=True)
    parser.add_argument("--expected-build", required=True)
    parser.add_argument("--expected-udid", action="append", default=[])
    parser.add_argument("--public-ipa-url", help="download and compare SHA-256 with --ipa")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ipa = args.ipa.expanduser().resolve()
    failures: list[str] = []
    report: dict = {"ipa": str(ipa), "checks": {}}
    if not ipa.is_file():
        raise SystemExit(f"missing IPA: {ipa}")
    local_hash = hashlib.sha256(ipa.read_bytes()).hexdigest()
    report["ipa_sha256"] = local_hash

    with tempfile.TemporaryDirectory(prefix="ios-release-validate-") as temp_dir:
        root = Path(temp_dir)
        with zipfile.ZipFile(ipa) as archive:
            archive.extractall(root)
        apps = list((root / "Payload").glob("*.app"))
        if len(apps) != 1:
            raise SystemExit("IPA must contain exactly one top-level Payload/*.app")
        app = apps[0]
        info = plistlib.loads((app / "Info.plist").read_bytes())
        actual_bundle = str(info.get("CFBundleIdentifier", ""))
        actual_build = str(info.get("CFBundleVersion", ""))
        report["checks"]["bundle_id"] = actual_bundle
        report["checks"]["build"] = actual_build
        if actual_bundle != args.expected_bundle_id:
            failures.append(f"bundle ID mismatch: {actual_bundle}")
        if actual_build != str(args.expected_build):
            failures.append(f"build mismatch: {actual_build}")

        provision_path = app / "embedded.mobileprovision"
        if not provision_path.is_file():
            failures.append("embedded.mobileprovision missing")
        else:
            provision = decode_provision(provision_path)
            devices = set(provision.get("ProvisionedDevices", []))
            report["checks"]["provisioned_device_count"] = len(devices)
            report["checks"]["is_device_limited"] = not provision.get("ProvisionsAllDevices", False)
            get_task_allow = bool(provision.get("Entitlements", {}).get("get-task-allow", False))
            report["checks"]["get_task_allow"] = get_task_allow
            missing = sorted(set(args.expected_udid) - devices)
            if missing:
                failures.append("expected UDID absent from provisioning profile: " + ", ".join(missing))
            if provision.get("ProvisionsAllDevices"):
                failures.append("profile is not Ad Hoc: ProvisionsAllDevices is true")
            if get_task_allow:
                failures.append("profile permits debugging and is not a distribution profile")

        if shutil.which("codesign"):
            verify = subprocess.run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", str(app)], capture_output=True, text=True)
            report["checks"]["codesign_ok"] = verify.returncode == 0
            if verify.returncode != 0:
                failures.append("codesign verification failed: " + (verify.stderr or verify.stdout)[-500:])

    manifest = plistlib.loads(load_bytes(args.manifest))
    try:
        item = manifest["items"][0]
        metadata = item["metadata"]
        package_url = next(asset["url"] for asset in item["assets"] if asset["kind"] == "software-package")
    except (KeyError, IndexError, StopIteration, TypeError) as exc:
        raise SystemExit(f"invalid OTA manifest structure: {exc}") from exc
    report["checks"]["manifest_package_url"] = package_url
    if metadata.get("bundle-identifier") != args.expected_bundle_id:
        failures.append("manifest bundle ID mismatch")
    if str(metadata.get("bundle-version")) != str(args.expected_build):
        failures.append("manifest build mismatch")
    if not str(package_url).startswith("https://"):
        failures.append("manifest package URL is not HTTPS")

    if args.public_ipa_url:
        public_bytes = load_bytes(args.public_ipa_url)
        public_hash = hashlib.sha256(public_bytes).hexdigest()
        report["public_ipa_sha256"] = public_hash
        if public_hash != local_hash:
            failures.append("public IPA SHA-256 does not match local release")

    report["ok"] = not failures
    report["failures"] = failures
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
