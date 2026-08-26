#!/usr/bin/env python3
"""Create a branded, secret-initialized iOS Ad Hoc enrollment portal."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import secrets
import shutil
import struct
import urllib.parse
import zlib
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = SKILL_ROOT / "assets" / "installer-template"


def existing_path(value: str, *, directory: bool = False) -> Path:
    path = Path(value).expanduser().resolve()
    if directory and not path.is_dir():
        raise argparse.ArgumentTypeError(f"not a directory: {path}")
    if not directory and not path.is_file():
        raise argparse.ArgumentTypeError(f"not a file: {path}")
    return path


def https_url(value: str) -> str:
    parsed = urllib.parse.urlparse(value.rstrip("/"))
    if parsed.scheme != "https" or not parsed.hostname or parsed.path not in {"", "/"}:
        raise argparse.ArgumentTypeError("base URL must be an HTTPS origin, for example https://install.company.example")
    return value.rstrip("/")


def bundle_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", value):
        raise argparse.ArgumentTypeError("invalid iOS bundle identifier")
    return value


def color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9A-Fa-f]{6}", value):
        raise argparse.ArgumentTypeError("brand color must use #RRGGBB")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload) & 0xFFFFFFFF)


def solid_png(path: Path, size: int, rgb: tuple[int, int, int]) -> None:
    row = b"\x00" + bytes((*rgb, 255)) * size
    raw = row * size
    png = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )
    path.write_bytes(png)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--app-name", required=True)
    parser.add_argument("--app-short-name", required=True)
    parser.add_argument("--organization", required=True)
    parser.add_argument("--bundle-id", required=True, type=bundle_id)
    parser.add_argument("--bundle-version", required=True)
    parser.add_argument("--marketing-version", default="1.0.0")
    parser.add_argument("--base-url", required=True, type=https_url)
    parser.add_argument("--archive-path", required=True, type=lambda v: existing_path(v, directory=True))
    parser.add_argument("--ipa-path", required=True, type=existing_path)
    parser.add_argument("--export-options-path", required=True, type=existing_path)
    parser.add_argument("--icon-57", type=existing_path)
    parser.add_argument("--icon-512", type=existing_path)
    parser.add_argument("--brand-color", default="#E6322F", type=color)
    parser.add_argument("--listen-port", default=8877, type=int)
    parser.add_argument("--token-ttl-minutes", default=1440, type=int)
    parser.add_argument("--start-rate-limit-count", default=100, type=int)
    parser.add_argument("--start-rate-window-seconds", default=600, type=int)
    parser.add_argument("--data-retention-days", default=30, type=int)
    parser.add_argument("--profile-sign-identity", default="")
    parser.add_argument("--profile-sign-certificate-path", default="")
    parser.add_argument("--profile-sign-chain-path", default="")
    parser.add_argument("--profile-sign-private-key-path", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.expanduser().resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TEMPLATE, output, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    assets = output / "assets"
    assets.mkdir(exist_ok=True)
    icon_57 = assets / "icon-57.png"
    icon_512 = assets / "icon-512.png"
    if args.icon_57:
        shutil.copy2(args.icon_57, icon_57)
    else:
        solid_png(icon_57, 57, args.brand_color)
    if args.icon_512:
        shutil.copy2(args.icon_512, icon_512)
    else:
        solid_png(icon_512, 512, args.brand_color)

    config = json.loads((output / "config.example.json").read_text("utf-8"))
    ipa_filename = re.sub(r"[^A-Za-z0-9._-]+", "-", args.app_short_name).strip("-.") or "App"
    if not ipa_filename.lower().endswith(".ipa"):
        ipa_filename += ".ipa"
    config.update({
        "organization": args.organization,
        "service_name": f"{args.app_short_name} 裝置登記",
        "app_name": args.app_name,
        "app_short_name": args.app_short_name,
        "bundle_id": args.bundle_id,
        "bundle_version": str(args.bundle_version),
        "marketing_version": args.marketing_version,
        "base_url": args.base_url,
        "brand_color": "#{:02X}{:02X}{:02X}".format(*args.brand_color),
        "listen_port": args.listen_port,
        "token_ttl_minutes": args.token_ttl_minutes,
        "start_rate_limit_count": args.start_rate_limit_count,
        "start_rate_window_seconds": args.start_rate_window_seconds,
        "data_retention_days": args.data_retention_days,
        "profile_identifier_prefix": args.bundle_id + ".enrollment",
        "profile_filename": ipa_filename.removesuffix(".ipa") + "-device-registration.mobileconfig",
        "app_ipa_filename": ipa_filename,
        "archive_path": str(args.archive_path),
        "initial_ipa_path": str(args.ipa_path),
        "export_options_path": str(args.export_options_path),
        "icon_57_path": str(icon_57),
        "icon_512_path": str(icon_512),
        "profile_sign_identity": args.profile_sign_identity,
        "profile_sign_certificate_path": str(Path(args.profile_sign_certificate_path).expanduser().resolve()) if args.profile_sign_certificate_path else "",
        "profile_sign_chain_path": str(Path(args.profile_sign_chain_path).expanduser().resolve()) if args.profile_sign_chain_path else "",
        "profile_sign_private_key_path": str(Path(args.profile_sign_private_key_path).expanduser().resolve()) if args.profile_sign_private_key_path else "",
    })
    (output / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", "utf-8")

    data_key = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
    portal_token = secrets.token_urlsafe(32)
    env_text = (
        f"DATA_ENCRYPTION_KEY={data_key}\n"
        f"INSTALL_PORTAL_TOKEN={portal_token}\n"
        "ASC_ISSUER_ID=\n"
        "ASC_KEY_ID=\n"
        "ASC_PRIVATE_KEY_PATH=\n"
        "OPENSSL_BIN=/opt/homebrew/bin/openssl\n"
    )
    env_path = output / ".env"
    env_path.write_text(env_text, "utf-8")
    env_path.chmod(0o600)
    env_example = output / "env.example"
    shutil.copy2(env_example, output / ".env.example")
    env_example.unlink()

    for script in (output / "scripts").glob("*.sh"):
        script.chmod(0o755)
    for directory in (output / "data" / "profiles", output / "logs", output / "runtime"):
        directory.mkdir(parents=True, exist_ok=True)

    link = f"{args.base_url}/?access={urllib.parse.quote(portal_token)}"
    link_file = output / "installer-link.txt"
    link_file.write_text(link + "\n", "utf-8")
    link_file.chmod(0o600)
    print(json.dumps({"output": str(output), "installer_url": link, "next": "fill App Store Connect API values in .env, configure profile signing, then run scripts/setup.sh"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
