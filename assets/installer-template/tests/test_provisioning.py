from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provisioning


class ExportAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.config = {"archive_path": "/fixture/App.xcarchive", "export_options_path": "/fixture/ExportOptions.plist"}
        self.env = {"ASC_PRIVATE_KEY_PATH": "/fixture/key.p8", "ASC_KEY_ID": "FIXTURE_KEY", "ASC_ISSUER_ID": "FIXTURE_ISSUER"}

    def test_omitted_mode_preserves_api_key_authentication(self):
        command = provisioning.export_command(self.config, self.env, "/fixture/export")
        self.assertIn("-allowProvisioningUpdates", command)
        for flag, key in (("-authenticationKeyPath", "ASC_PRIVATE_KEY_PATH"), ("-authenticationKeyID", "ASC_KEY_ID"), ("-authenticationKeyIssuerID", "ASC_ISSUER_ID")):
            self.assertEqual(command[command.index(flag) + 1], self.env[key])

    def test_explicit_api_key_matches_default(self):
        self.assertEqual(
            provisioning.export_command(self.config, self.env, "/fixture/export"),
            provisioning.export_command({**self.config, "export_authentication": "api-key"}, self.env, "/fixture/export"),
        )

    def test_xcode_account_omits_all_api_authentication_flags(self):
        command = provisioning.export_command({**self.config, "export_authentication": "xcode-account"}, self.env, "/fixture/export")
        self.assertEqual(command, ["xcodebuild", "-exportArchive", "-archivePath", self.config["archive_path"], "-exportPath", "/fixture/export", "-exportOptionsPlist", self.config["export_options_path"], "-allowProvisioningUpdates"])
        for secret in self.env.values():
            self.assertNotIn(secret, command)

    def test_xcode_export_does_not_require_api_credentials_for_command(self):
        self.assertIn("-allowProvisioningUpdates", provisioning.export_command({**self.config, "export_authentication": "xcode-account"}, {}, "/fixture/export"))

    def test_missing_api_credentials_does_not_fall_back_to_account(self):
        with self.assertRaisesRegex(ValueError, "all three ASC"):
            provisioning.export_command(self.config, {}, "/fixture/export")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "export_authentication"):
            provisioning.export_command({**self.config, "export_authentication": "auto"}, self.env, "/fixture/export")

    def test_export_failure_does_not_retry_as_another_identity_or_replace_ipa(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "App.xcarchive"
            archive.mkdir()
            options = root / "ExportOptions.plist"
            options.write_bytes(b"fixture")
            public = root / "App.ipa"
            public.write_bytes(b"last-verified-release")
            config = {**self.config, "archive_path": str(archive), "export_options_path": str(options)}
            result = SimpleNamespace(returncode=70, stdout="", stderr="Cloud signing permission error")
            with mock.patch.object(provisioning.subprocess, "run", return_value=result) as run:
                with self.assertRaisesRegex(RuntimeError, "匯出失敗"):
                    provisioning.export_ipa(config, self.env, public, "FIXTURE_UDID")
            self.assertEqual(run.call_count, 1)
            self.assertIn("-authenticationKeyID", run.call_args.args[0])
            self.assertEqual(public.read_bytes(), b"last-verified-release")

    def test_validation_failure_never_publishes_an_ineligible_ipa(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "App.xcarchive"
            archive.mkdir()
            options = root / "ExportOptions.plist"
            options.write_bytes(b"fixture")
            public = root / "App.ipa"
            public.write_bytes(b"last-verified-release")
            config = {**self.config, "archive_path": str(archive), "export_options_path": str(options), "export_authentication": "xcode-account"}
            def successful_export(command, **kwargs):
                (Path(command[command.index("-exportPath") + 1]) / "App.ipa").write_bytes(b"unvalidated-candidate")
                return SimpleNamespace(returncode=0, stdout="", stderr="")
            with mock.patch.object(provisioning.subprocess, "run", side_effect=successful_export), mock.patch.object(provisioning, "_validate_exported_ipa", side_effect=RuntimeError("new device is absent")) as validate:
                with self.assertRaisesRegex(RuntimeError, "new device is absent"):
                    provisioning.export_ipa(config, self.env, public, "FIXTURE_UDID")
            self.assertEqual(validate.call_args.args[2], "FIXTURE_UDID")
            self.assertEqual(public.read_bytes(), b"last-verified-release")


if __name__ == "__main__":
    unittest.main()
