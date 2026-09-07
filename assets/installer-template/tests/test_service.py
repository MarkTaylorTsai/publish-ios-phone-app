from __future__ import annotations

import base64
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATA_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"0" * 32).decode("ascii"))
os.environ.setdefault("INSTALL_PORTAL_TOKEN", "fixture-portal-token-0123456789")

import provisioning
import server
import templates


def make_device_cms(payload: bytes, ca_common_name: str = "Apple iPhone Device CA") -> tuple[bytes, bytes]:
    now = datetime.now(timezone.utc)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Apple Inc."),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Apple iPhone"),
        x509.NameAttribute(NameOID.COMMON_NAME, ca_common_name),
    ])
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=730))
        .not_valid_after(now - timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fixture iPhone")]))
        .issuer_name(ca_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=730))
        .not_valid_after(now - timedelta(days=365))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, False, False), critical=True)
        .sign(ca_key, hashes.SHA256())
    )
    cms = (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(payload)
        .add_signer(leaf_cert, leaf_key, hashes.SHA256())
        .add_certificate(ca_cert)
        .sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.Binary])
    )
    return cms, ca_cert.public_bytes(serialization.Encoding.PEM)


class TemplateTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "config.json").read_text())

    def test_profile_requests_only_minimum_attributes(self):
        raw = templates.profile_plist(self.config, "A" * 43, "00000000-0000-0000-0000-000000000001")
        payload = plistlib.loads(raw)
        self.assertEqual(payload["PayloadType"], "Profile Service")
        self.assertEqual(payload["PayloadContent"]["DeviceAttributes"], ["UDID", "PRODUCT", "VERSION"])
        self.assertNotIn("IMEI", payload["PayloadContent"]["DeviceAttributes"])
        self.assertEqual(payload["PayloadContent"]["Challenge"], "A" * 43)

    def test_manifest_contract(self):
        payload = plistlib.loads(templates.manifest_plist(self.config))
        item = payload["items"][0]
        self.assertEqual(item["metadata"]["bundle-identifier"], self.config["bundle_id"])
        package = next(x for x in item["assets"] if x["kind"] == "software-package")
        self.assertTrue(package["url"].startswith("https://"))
        self.assertTrue(package["url"].endswith("/downloads/" + self.config["app_ipa_filename"]))

    def test_consent_page_discloses_scope(self):
        page = templates.enrollment_page(self.config, "A" * 43, {"status": "new"})
        for text in ("UDID", "產品型號", "iOS 版本", "不會取得照片", "同意"):
            self.assertIn(text, page)

    def test_landing_page_has_explicit_start(self):
        page = templates.landing_page(self.config, "fixture-access-token")
        self.assertIn('method="post" action="/start"', page)
        self.assertIn('name="access" value="fixture-access-token"', page)
        self.assertIn("開始 iPhone 安裝", page)

    def test_line_browser_page_blocks_flow_and_explains_safari_handoff(self):
        page = templates.line_browser_page(self.config, "/e/TEST_TOKEN")
        self.assertNotIn('action="/start"', page)
        self.assertNotIn("profile.mobileconfig", page)
        for text in (
            "請改用 Safari 繼續",
            "LINE 內建瀏覽器不支援",
            "立即改用 Safari 開啟",
            "x-safari-" + self.config["base_url"] + "/e/TEST_TOKEN",
            "使用預設瀏覽器開啟",
            "在 Safari 中開啟",
            "複製安裝網址",
        ):
            self.assertIn(text, page)
    def test_line_user_agent_detection_is_explicit(self):
        self.assertTrue(server.is_line_user_agent("Mozilla/5.0 Mobile LINE/15.1.0"))
        self.assertTrue(server.is_line_user_agent("Mozilla/5.0; Line/14.0.0"))
        self.assertFalse(server.is_line_user_agent("Mozilla/5.0 Mobile/15E148 Safari/604.1"))
        self.assertFalse(server.is_line_user_agent("Mozilla/5.0 Chrome/140.0"))

    def test_profile_download_instructions_include_both_settings_paths(self):
        page = templates.enrollment_page(
            self.config,
            "A" * 43,
            {"status": "profile_downloaded", "consented_at": "2026-08-25T00:00:00Z"},
        )
        for text in (
            "此網站正嘗試下載設定描述檔",
            "設定首頁",
            "已下載描述檔",
            "設定 → 一般 → VPN 與裝置管理",
            "描述檔與裝置管理",
            self.config["service_name"],
            "右上角",
            "手機解鎖密碼",
            "回到 Safari",
        ):
            self.assertIn(text, page)
        self.assertNotIn('<div class="steps">', page)

    def test_ready_install_button_is_single_use_and_persists_clicked_state(self):
        page = templates.enrollment_page(
            self.config,
            "A" * 43,
            {"status": "ready", "consented_at": "2026-08-25T00:00:00Z"},
        )
        for text in (
            'id="install-app"',
            f"安裝 {self.config['app_short_name']}（只需點一次）",
            "已開始下載，請回到手機主畫面",
            f"查看「{self.config['app_short_name']}」圖示是否已開始下載",
            "請勿重複點擊安裝",
            "localStorage.setItem",
            "aria-disabled",
            "removeAttribute('href')",
            "window.location.href=destination",
            'id="developer-mode-guide" class="guide hidden"',
            "developerModeGuide.classList.remove('hidden')",
            "設定」→「隱私權與安全性",
            "Window → Devices and Simulators",
            f"ios-install-clicked:{self.config['bundle_id']}:{'A' * 43}:{self.config['bundle_version']}",
        ):
            self.assertIn(text, page)
        self.assertNotIn("下載後，請照這條路徑操作", page)
        self.assertNotIn('id="app-install-guide"', page)
        self.assertNotIn("{app_short}", page)

    def test_portal_access_token_is_required_and_compared(self):
        self.assertTrue(server.portal_access_allowed("fixture-portal-token-0123456789"))
        self.assertFalse(server.portal_access_allowed(""))
        self.assertFalse(server.portal_access_allowed("wrong-token"))


class RateLimitTests(unittest.TestCase):
    def setUp(self):
        server.START_RATE.clear()

    def tearDown(self):
        server.START_RATE.clear()

    def test_start_link_limit_allows_one_hundred_requests_per_window(self):
        self.assertEqual(server.START_RATE_LIMIT_COUNT, 100)
        self.assertEqual(server.START_RATE_WINDOW_SECONDS, 600)
        with mock.patch.object(server.time, "time", return_value=1_000.0):
            for _ in range(100):
                self.assertTrue(server.allow_start("203.0.113.10"))
            self.assertFalse(server.allow_start("203.0.113.10"))


class JWTTests(unittest.TestCase):
    def test_der_signature_conversion(self):
        r = bytes.fromhex("01" * 32)
        s = bytes.fromhex("02" * 32)
        der = b"\x30\x44\x02\x20" + r + b"\x02\x20" + s
        self.assertEqual(provisioning._der_ecdsa_to_raw(der), r + s)

    def test_udid_formats_are_explicit(self):
        import re
        pattern = re.compile(r"^(?:[0-9A-Fa-f]{40}|[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16})$")
        self.assertTrue(pattern.fullmatch("0" * 40))
        self.assertTrue(pattern.fullmatch("00008110-000A6DE901F1801E"))
        self.assertFalse(pattern.fullmatch("not-a-device"))


class ProvisioningFailureTests(unittest.TestCase):
    def exercise_failure(self, *, during_export: bool):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(server, "DB_PATH", Path(temporary) / "enrollment.sqlite3"):
            server.init_db()
            token = server.create_enrollment()
            server.update(token, status="collected", consented_at=server.now_iso(), device_label="Fixture iPhone", udid_sha256="0" * 64, udid_encrypted=server.FERNET.encrypt(b"0" * 40))
            with mock.patch.object(provisioning, "configured", return_value=True), mock.patch.object(provisioning, "register_device", side_effect=None if during_export else RuntimeError("PRIVATE_API_DETAIL")) as register, mock.patch.object(provisioning, "export_ipa", side_effect=RuntimeError("PRIVATE_SIGNING_DETAIL")) as export, mock.patch.object(server.logging, "exception"):
                server.provision_job(token)
            record = server.enrollment(token)
            self.assertEqual(record["status"], "error")
            self.assertTrue(record["consented_at"])
            self.assertTrue(record["udid_encrypted"])
            self.assertNotIn("PRIVATE_", record["public_error"])
            self.assertIsNone(record["ready_at"])
            register.assert_called_once()
            if during_export:
                export.assert_called_once()
                self.assertTrue(record["registered_at"])
                self.assertIn("Apple 裝置已登記", record["public_error"])
                self.assertIn("簽章／匯出", record["public_error"])
            else:
                export.assert_not_called()
                self.assertIsNone(record["registered_at"])
                self.assertIn("Apple 裝置登記尚未完成", record["public_error"])

    def test_export_failure_preserves_successful_apple_registration(self):
        self.exercise_failure(during_export=True)

    def test_registration_failure_is_not_misreported_as_signing_failure(self):
        self.exercise_failure(during_export=False)


class CMSVerificationTests(unittest.TestCase):
    def test_selected_openssl_supports_required_cms_verification_options(self):
        result = subprocess.run(
            [server.OPENSSL_BIN, "cms", "-help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        help_text = result.stdout + result.stderr
        for option in ("-no_check_time", "-partial_chain", "-auth_level"):
            self.assertIn(option, help_text)

    def test_pinned_apple_device_ca_fingerprint(self):
        cert = x509.load_pem_x509_certificate((ROOT / "certs/apple-iphone-device-ca.pem").read_bytes())
        self.assertEqual(
            cert.fingerprint(hashes.SHA256()).hex(),
            "76f27d00e1333bc88de0e2916c38c9a7f2b75774c25a794c092a80e3c4c66cce",
        )

    def test_cms_signature_and_pinned_device_ca_are_verified_without_time_check(self):
        payload = plistlib.dumps({"CHALLENGE": "T", "UDID": "0" * 40})
        cms, ca_pem = make_device_cms(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            ca_path = Path(temp_dir) / "device-ca.pem"
            ca_path.write_bytes(ca_pem)
            self.assertEqual(server.decode_cms(cms, ca_path), payload)

    def test_cms_from_different_ca_with_same_name_is_rejected(self):
        payload = plistlib.dumps({"CHALLENGE": "T", "UDID": "0" * 40})
        _, trusted_ca = make_device_cms(payload)
        untrusted_cms, _ = make_device_cms(payload)
        with tempfile.TemporaryDirectory() as temp_dir:
            ca_path = Path(temp_dir) / "trusted-device-ca.pem"
            ca_path.write_bytes(trusted_ca)
            with self.assertRaisesRegex(ValueError, "invalid CMS signature or Apple device chain"):
                server.decode_cms(untrusted_cms, ca_path)

    def test_cms_from_modern_apple_device_ca_can_chain_to_system_roots(self):
        payload = plistlib.dumps({"CHALLENGE": "T", "UDID": "0" * 40})
        cms, modern_ca = make_device_cms(payload, "Apple Modern Device CA")
        with tempfile.TemporaryDirectory() as temp_dir:
            roots_path = Path(temp_dir) / "system-roots.pem"
            roots_path.write_bytes(modern_ca)
            self.assertEqual(
                server.decode_cms(
                    cms,
                    ROOT / "certs/apple-iphone-device-ca.pem",
                    roots_path,
                ),
                payload,
            )

    def test_valid_cms_advances_enrollment_to_collected(self):
        original_db = server.DB_PATH
        original_decode = server.decode_cms
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            server.DB_PATH = temp / "enrollment.sqlite3"
            server.init_db()
            token = server.create_enrollment()
            server.update(token, status="consented", consented_at=server.now_iso(), device_label="Fixture iPhone")
            raw = plistlib.dumps({
                "CHALLENGE": token,
                "UDID": "00008110-000A6DE901F1801E",
                "PRODUCT": "iPhone14,2",
                "VERSION": "26.0",
            })
            cms, ca_pem = make_device_cms(raw)
            ca_path = temp / "device-ca.pem"
            ca_path.write_bytes(ca_pem)
            try:
                with mock.patch.object(
                    server,
                    "decode_cms",
                    side_effect=lambda body: original_decode(body, ca_path, ca_path),
                ), mock.patch.object(server, "provision_job") as provision:
                    decoded = server.process_device_payload(token, cms)
                    provision.assert_called_once_with(token)
                record = server.enrollment(token)
                self.assertEqual(decoded["CHALLENGE"], token)
                self.assertEqual(record["status"], "collected")
                self.assertEqual(server.decrypt_udid(record), "00008110-000A6DE901F1801E")
                self.assertEqual(record["product"], "iPhone14,2")
            finally:
                server.DB_PATH = original_db


if __name__ == "__main__":
    unittest.main()
