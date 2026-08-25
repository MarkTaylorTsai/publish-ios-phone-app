from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import plistlib
import re
import secrets
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from cryptography.fernet import Fernet, InvalidToken

import provisioning
import templates


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
LOGS = ROOT / "logs"
RUNTIME = ROOT / "runtime"
for directory in (DATA, LOGS, RUNTIME, DATA / "profiles"):
    directory.mkdir(parents=True, exist_ok=True)

CONFIG = json.loads((ROOT / "config.json").read_text("utf-8"))
DB_PATH = DATA / "enrollment.sqlite3"
IPA_FILENAME = str(CONFIG.get("app_ipa_filename", "App.ipa"))
IPA_PATH = DATA / IPA_FILENAME
UDID_RE = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16})$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,80}$")
BUILD_LOCK = threading.Lock()
RATE_LOCK = threading.Lock()
START_RATE: dict[str, list[float]] = {}


def load_dotenv() -> dict[str, str]:
    values = dict(os.environ)
    path = ROOT / ".env"
    if path.exists():
        for raw in path.read_text("utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


ENV = load_dotenv()
if not ENV.get("DATA_ENCRYPTION_KEY"):
    raise SystemExit("DATA_ENCRYPTION_KEY 未設定，請先執行 scripts/setup.sh")
if not ENV.get("INSTALL_PORTAL_TOKEN"):
    raise SystemExit("INSTALL_PORTAL_TOKEN 未設定；公開自助登記入口必須使用不可猜測的存取權杖")
FERNET = Fernet(ENV["DATA_ENCRYPTION_KEY"].encode("ascii"))


def find_modern_openssl() -> str:
    candidates = [
        ENV.get("OPENSSL_BIN", ""),
        "/opt/homebrew/bin/openssl",
        "/usr/local/bin/openssl",
        shutil.which("openssl") or "",
    ]
    for candidate in dict.fromkeys(candidates):
        if not candidate or not Path(candidate).is_file():
            continue
        probe = subprocess.run([candidate, "cms", "-help"], capture_output=True, text=True, timeout=10)
        help_text = probe.stdout + probe.stderr
        if all(flag in help_text for flag in ("-no_check_time", "-partial_chain", "-auth_level")):
            return candidate
    raise SystemExit("需要支援現代 CMS 驗證選項的 OpenSSL")


OPENSSL_BIN = find_modern_openssl()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOGS / "service.log"), logging.StreamHandler()],
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_line_user_agent(user_agent: str) -> bool:
    return bool(re.search(r"(?:^|[ /;])LINE/[0-9]", user_agent or "", re.IGNORECASE))


def portal_access_allowed(value: str) -> bool:
    expected = ENV.get("INSTALL_PORTAL_TOKEN", "")
    return bool(expected) and secrets.compare_digest(value or "", expected)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS enrollments (
          token TEXT PRIMARY KEY,
          created_at TEXT NOT NULL,
          expires_at INTEGER NOT NULL,
          consented_at TEXT,
          device_label TEXT,
          status TEXT NOT NULL,
          profile_uuid TEXT NOT NULL,
          profile_downloaded_at TEXT,
          collected_at TEXT,
          udid_encrypted BLOB,
          udid_sha256 TEXT,
          product TEXT,
          ios_version TEXT,
          registered_at TEXT,
          ready_at TEXT,
          public_error TEXT,
          internal_error TEXT,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS enrollments_status_idx ON enrollments(status);
        """)


def create_enrollment() -> str:
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with db() as conn:
        conn.execute(
            "INSERT INTO enrollments(token,created_at,expires_at,status,profile_uuid,updated_at) VALUES(?,?,?,?,?,?)",
            (token, now_iso(), now + int(CONFIG["token_ttl_minutes"]) * 60, "new", str(uuid.uuid4()).upper(), now_iso()),
        )
    return token


def enrollment(token: str) -> dict | None:
    if not TOKEN_RE.fullmatch(token):
        return None
    with db() as conn:
        row = conn.execute("SELECT * FROM enrollments WHERE token=?", (token,)).fetchone()
    if not row:
        return None
    result = dict(row)
    result["expired"] = int(result["expires_at"]) < int(time.time()) and result["status"] not in {"ready"}
    return result


def update(token: str, **fields) -> None:
    fields["updated_at"] = now_iso()
    sql = ",".join(f"{key}=?" for key in fields)
    with db() as conn:
        conn.execute(f"UPDATE enrollments SET {sql} WHERE token=?", (*fields.values(), token))


def public_record(record: dict) -> dict:
    return {"status": record["status"], "updated_at": record["updated_at"], "error": record.get("public_error")}


def allow_start(ip: str) -> bool:
    cutoff = time.time() - 600
    with RATE_LOCK:
        recent = [stamp for stamp in START_RATE.get(ip, []) if stamp > cutoff]
        if len(recent) >= 5:
            START_RATE[ip] = recent
            return False
        recent.append(time.time())
        START_RATE[ip] = recent
        return True


def sign_profile(unsigned: bytes, destination: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="ios-install-profile-") as temp_dir:
        source = Path(temp_dir) / "unsigned.mobileconfig"
        signed = Path(temp_dir) / "signed.mobileconfig"
        source.write_bytes(unsigned)
        certificate_value = str(CONFIG.get("profile_sign_certificate_path", "")).strip()
        private_key_value = str(CONFIG.get("profile_sign_private_key_path", "")).strip()
        chain_value = str(CONFIG.get("profile_sign_chain_path", "")).strip()
        identity = str(CONFIG.get("profile_sign_identity", "")).strip()
        certificate = Path(certificate_value)
        private_key = Path(private_key_value)
        chain = Path(chain_value)
        if all((certificate_value, private_key_value, chain_value)) and all(path.is_file() for path in (certificate, private_key, chain)):
            command = [OPENSSL_BIN, "cms", "-sign", "-binary", "-in", str(source), "-signer", str(certificate), "-inkey", str(private_key), "-certfile", str(chain), "-outform", "DER", "-nosmimecap", "-nodetach", "-out", str(signed)]
        elif identity:
            command = ["security", "cms", "-S", "-u", "6", "-N", identity, "-H", "SHA256", "-i", str(source), "-o", str(signed)]
        else:
            raise RuntimeError("未設定描述檔 CMS 簽章憑證或 keychain identity")
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
        if result.returncode != 0:
            raise RuntimeError("描述檔簽章失敗：" + (result.stderr or result.stdout)[-1000:])
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_suffix(".new")
        shutil.copy2(signed, staging)
        os.replace(staging, destination)


def decode_cms(
    body: bytes,
    device_ca_path: Path | None = None,
    system_roots_path: Path | None = None,
) -> bytes:
    if len(body) > 2_000_000:
        raise ValueError("CMS payload too large")
    with tempfile.TemporaryDirectory(prefix="ios-device-cms-") as temp_dir:
        source = Path(temp_dir) / "device.der"
        decoded = Path(temp_dir) / "device.plist"
        signer = Path(temp_dir) / "signer.pem"
        trust = Path(temp_dir) / "device-trust.pem"
        source.write_bytes(body)
        device_ca = device_ca_path or (ROOT / "certs" / "apple-iphone-device-ca.pem")
        if not device_ca.exists():
            raise ValueError("missing Apple iPhone Device CA")
        system_roots = system_roots_path or (DATA / "system-roots.pem")
        if not system_roots.exists():
            raise ValueError("missing system trust store")
        trust.write_bytes(system_roots.read_bytes() + b"\n" + device_ca.read_bytes())
        result = subprocess.run(
            [
                OPENSSL_BIN, "cms", "-verify", "-binary", "-inform", "DER",
                "-in", str(source), "-CAfile", str(trust), "-purpose", "any",
                "-no_check_time", "-auth_level", "0", "-partial_chain",
                "-trusted_first", "-signer", str(signer), "-out", str(decoded),
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()
            raise ValueError("invalid CMS signature or Apple device chain: " + (detail[-1][:300] if detail else "unknown OpenSSL error"))
        identity = subprocess.run(
            [OPENSSL_BIN, "x509", "-in", str(signer), "-noout", "-subject", "-issuer"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout
        if "Apple" not in identity or "Device" not in identity:
            raise ValueError("CMS signer is not an Apple device identity")
        return decoded.read_bytes()


def process_device_payload(token: str, body: bytes) -> dict:
    record = enrollment(token)
    if not record or record["expired"] or not record.get("consented_at"):
        raise ValueError("invalid or expired enrollment")
    payload = plistlib.loads(decode_cms(body))
    challenge = payload.get("CHALLENGE") or payload.get("Challenge")
    if isinstance(challenge, bytes):
        challenge = challenge.decode("utf-8", "strict")
    if not secrets.compare_digest(str(challenge or ""), token):
        raise ValueError("challenge mismatch")
    udid = str(payload.get("UDID", "")).upper()
    if not UDID_RE.fullmatch(udid):
        raise ValueError("invalid UDID format")
    digest = hashlib.sha256(udid.encode()).hexdigest()
    update(
        token,
        status="collected",
        collected_at=now_iso(),
        udid_encrypted=FERNET.encrypt(udid.encode()),
        udid_sha256=digest,
        product=str(payload.get("PRODUCT", ""))[:100],
        ios_version=str(payload.get("VERSION", ""))[:100],
        public_error=None,
        internal_error=None,
    )
    logging.info("device_collected token=%s udid_sha256=%s", token[:8], digest[:12])
    threading.Thread(target=provision_job, args=(token,), daemon=True).start()
    return payload


def decrypt_udid(record: dict) -> str:
    try:
        return FERNET.decrypt(record["udid_encrypted"]).decode("ascii")
    except (InvalidToken, TypeError) as exc:
        raise RuntimeError("UDID 解密失敗") from exc


def provision_job(token: str) -> None:
    with BUILD_LOCK:
        record = enrollment(token)
        if not record or record["status"] == "ready":
            return
        try:
            if not provisioning.configured(ENV):
                update(token, status="collected", public_error="裝置資料已收到，正在等待 Apple 自動簽章服務完成設定。")
                return
            update(token, status="registering")
            udid = decrypt_udid(record)
            label = (record.get("device_label") or f"iPhone customer {record['udid_sha256'][:8]}").strip()
            provisioning.register_device(udid, label, ENV)
            update(token, registered_at=now_iso(), status="exporting")
            provisioning.export_ipa(CONFIG, ENV, IPA_PATH, udid)
            update(token, status="ready", ready_at=now_iso(), public_error=None, internal_error=None)
            logging.info("provision_ready token=%s", token[:8])
        except Exception as exc:
            logging.exception("provision_failed token=%s", token[:8])
            update(token, status="error", public_error="Apple 裝置登記或簽章尚未完成，系統會保留資料供重新處理。", internal_error=str(exc)[-5000:])


def retry_pending() -> None:
    if not provisioning.configured(ENV):
        return
    with db() as conn:
        rows = conn.execute("SELECT token FROM enrollments WHERE status IN ('collected','error') ORDER BY created_at LIMIT 20").fetchall()
    for row in rows:
        threading.Thread(target=provision_job, args=(row["token"],), daemon=True).start()


def purge_expired() -> int:
    cutoff = int(time.time()) - int(CONFIG["data_retention_days"]) * 86400
    with db() as conn:
        rows = conn.execute("SELECT token FROM enrollments WHERE expires_at < ?", (cutoff,)).fetchall()
        conn.executemany("DELETE FROM enrollments WHERE token=?", [(row["token"],) for row in rows])
    for row in rows:
        (DATA / "profiles" / f"{row['token']}.mobileconfig").unlink(missing_ok=True)
    if rows:
        logging.info("expired_enrollments_purged count=%s", len(rows))
    return len(rows)


def cleanup_loop() -> None:
    while True:
        time.sleep(6 * 60 * 60)
        try:
            purge_expired()
        except Exception:
            logging.exception("expired_enrollment_cleanup_failed")


class Handler(BaseHTTPRequestHandler):
    server_version = "IOSInstallEnrollment/1"

    def log_message(self, fmt, *args):
        logging.info("http client=%s " + fmt, self.client_address[0], *args)

    def _headers(self, status=200, content_type="text/html; charset=utf-8", length=None, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if length is not None:
            self.send_header("Content-Length", str(length))
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()

    def send_bytes(self, body: bytes, status=200, content_type="text/html; charset=utf-8", extra=None):
        self._headers(status, content_type, len(body), extra)
        if self.command != "HEAD":
            self.wfile.write(body)

    def redirect(self, location: str, status=303):
        self._headers(status, "text/plain; charset=utf-8", 0, {"Location": location})

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if is_line_user_agent(self.headers.get("User-Agent", "")) and (path == "/" or path.startswith("/e/")):
            return self.send_bytes(
                templates.line_browser_page(CONFIG, self.path).encode(),
                extra={"Cache-Control": "no-store"},
            )
        if path == "/healthz":
            return self.send_bytes(b'{"ok":true}', content_type="application/json")
        if path.startswith("/.well-known/acme-challenge/"):
            name = path.rsplit("/", 1)[-1]
            if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", name):
                return self.send_bytes(b"Not Found", 404, "text/plain")
            challenge = DATA / "acme" / ".well-known" / "acme-challenge" / name
            if not challenge.exists():
                return self.send_bytes(b"Not Found", 404, "text/plain")
            return self.send_bytes(challenge.read_bytes(), content_type="text/plain")
        if path == "/":
            access = parse_qs(parsed_url.query).get("access", [""])[0]
            if not portal_access_allowed(access):
                return self.send_bytes(templates.error_page(CONFIG, "安裝連結無效或缺少授權碼。").encode(), 403)
            return self.send_bytes(templates.landing_page(CONFIG, access).encode())
        if path == "/manifest.plist":
            return self.send_bytes(templates.manifest_plist(CONFIG), content_type="application/xml")
        if path == f"/downloads/{IPA_FILENAME}":
            if not IPA_PATH.exists():
                return self.send_bytes(b"IPA not ready", 404, "text/plain; charset=utf-8")
            body = IPA_PATH.read_bytes()
            return self.send_bytes(body, content_type="application/octet-stream", extra={"Content-Disposition": f'attachment; filename="{IPA_FILENAME}"'})
        if path in {"/assets/icon-57.png", "/assets/icon-512.png"}:
            key = "icon_57_path" if "57" in path else "icon_512_path"
            file_path = Path(CONFIG[key])
            if not file_path.exists():
                return self.send_bytes(b"not found", 404, "text/plain")
            return self.send_bytes(file_path.read_bytes(), content_type="image/png")
        match = re.fullmatch(r"/e/([A-Za-z0-9_-]+)", path)
        if match:
            token = match.group(1)
            record = enrollment(token)
            if not record:
                return self.send_bytes(templates.error_page(CONFIG, "登記連結不存在。").encode(), 404)
            if record["expired"]:
                return self.send_bytes(templates.error_page(CONFIG, "這個登記連結已過期。").encode(), 410)
            return self.send_bytes(templates.enrollment_page(CONFIG, token, record).encode())
        match = re.fullmatch(r"/e/([A-Za-z0-9_-]+)/status", path)
        if match:
            record = enrollment(match.group(1))
            if not record:
                return self.send_bytes(b'{"error":"not_found"}', 404, "application/json")
            return self.send_bytes(json.dumps(public_record(record)).encode(), content_type="application/json")
        match = re.fullmatch(r"/e/([A-Za-z0-9_-]+)/profile\.mobileconfig", path)
        if match:
            token = match.group(1)
            record = enrollment(token)
            if not record or record["expired"] or not record.get("consented_at"):
                return self.send_bytes(templates.error_page(CONFIG, "請先完成同意流程。").encode(), 403)
            destination = DATA / "profiles" / f"{token}.mobileconfig"
            try:
                if not destination.exists():
                    sign_profile(templates.profile_plist(CONFIG, token, record["profile_uuid"]), destination)
                update(token, status="profile_downloaded", profile_downloaded_at=now_iso())
                filename = str(CONFIG.get("profile_filename", "ios-device-registration.mobileconfig"))
                return self.send_bytes(destination.read_bytes(), content_type="application/x-apple-aspen-config", extra={"Content-Disposition": f'attachment; filename="{filename}"'})
            except Exception as exc:
                logging.exception("profile_sign_failed")
                return self.send_bytes(templates.error_page(CONFIG, "描述檔產生失敗，請重新整理後再試。").encode(), 500)
        return self.send_bytes(b"Not Found", 404, "text/plain; charset=utf-8")

    def do_POST(self):
        path = urlparse(self.path).path
        if is_line_user_agent(self.headers.get("User-Agent", "")) and (path == "/start" or path.startswith("/e/")):
            return self.send_bytes(
                templates.line_browser_page(CONFIG, "/").encode(),
                extra={"Cache-Control": "no-store"},
            )
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 2_000_000:
            return self.send_bytes(b"Payload too large", 413, "text/plain")
        body = self.rfile.read(length)
        if path == "/start":
            values = parse_qs(body.decode("utf-8", "replace"))
            if not portal_access_allowed(values.get("access", [""])[0]):
                return self.send_bytes(templates.error_page(CONFIG, "安裝連結無效或已撤銷。").encode(), 403)
            client_ip = self.headers.get("CF-Connecting-IP") or self.client_address[0]
            if not allow_start(client_ip):
                return self.send_bytes(templates.error_page(CONFIG, "建立連結次數過多，請稍候再試。").encode(), 429)
            return self.redirect(f"/e/{create_enrollment()}")
        match = re.fullmatch(r"/e/([A-Za-z0-9_-]+)/consent", path)
        if match:
            token = match.group(1)
            record = enrollment(token)
            values = parse_qs(body.decode("utf-8", "replace"))
            if not record or record["expired"]:
                return self.send_bytes(templates.error_page(CONFIG, "登記連結不存在或已過期。").encode(), 410)
            if values.get("consent", [""])[0] != "yes":
                return self.send_bytes(templates.error_page(CONFIG, "請勾選資料使用同意後再繼續。").encode(), 400)
            label = values.get("device_label", [""])[0].strip()[:80]
            update(token, status="consented", consented_at=now_iso(), device_label=label)
            return self.redirect(f"/e/{token}")
        match = re.fullmatch(r"/profile/([A-Za-z0-9_-]+)", path)
        if match:
            token = match.group(1)
            try:
                process_device_payload(token, body)
                return self.redirect(f"{CONFIG['base_url']}/e/{token}", 301)
            except Exception:
                logging.exception("device_payload_rejected token=%s", token[:8])
                return self.send_bytes(b"Invalid device response", 400, "text/plain; charset=utf-8")
        return self.send_bytes(b"Not Found", 404, "text/plain; charset=utf-8")


def main() -> None:
    init_db()
    purge_expired()
    if not IPA_PATH.exists():
        existing = Path(CONFIG.get("initial_ipa_path", ""))
        if existing.exists():
            shutil.copy2(existing, IPA_PATH)
    retry_pending()
    threading.Thread(target=cleanup_loop, daemon=True).start()
    server = ThreadingHTTPServer((CONFIG["listen_host"], int(CONFIG["listen_port"])), Handler)
    logging.info("service_started host=%s port=%s asc_configured=%s", CONFIG["listen_host"], CONFIG["listen_port"], provisioning.configured(ENV))
    server.serve_forever()


if __name__ == "__main__":
    main()
