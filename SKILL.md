---
name: publish-ios-phone-app
description: Publish an existing iOS app through a branded HTTPS customer-consent portal that registers device UDIDs, exports an Ad Hoc IPA, and provides over-the-air installation. Use for install.company.example links outside App Store or TestFlight review.
---

# Publish iOS Phone App

Turn an already working iOS project into a branded link where a customer enters a device name, explicitly consents, installs a minimal registration profile, and then installs the correctly signed app from Safari.

## Choose the distribution path

Use this workflow for a known, limited group of customers whose devices may be registered for Ad Hoc distribution. Before implementing, read [references/apple-distribution-constraints.md](references/apple-distribution-constraints.md). Ad Hoc distribution has an Apple device quota and is not a public App Store replacement. If the requested audience cannot fit the quota or membership rules, explain the blocking constraint before touching DNS or Apple resources and select TestFlight, App Store, Custom Apps, or Unlisted distribution with the user.

## Required inputs

Inspect the existing project and derive values where possible:

- project type, workspace/project, scheme, configuration, bundle identifier, marketing version, and monotonically increasing build number;
- an Apple Developer team, signing identity, App Store Connect API issuer/key/private key, and permission to register devices and export an Ad Hoc build;
- a branded HTTPS origin such as `https://install.company.example`, its DNS/TLS deployment path, organization/app names, and icons;
- customer language, enrollment-link lifetime, and UDID retention period.

Ask only for values that cannot be discovered locally. Treat API keys, signing keys, portal tokens, raw UDIDs, and customer names as secrets. Authorization for source access does not by itself authorize DNS changes, Apple device registration, production deployment, or replacement of a live IPA; obtain specific confirmation immediately before each external mutation when it has not already been granted.

## Workflow

1. Inspect and test the existing app. Preserve a rollback copy. Resolve the native Xcode archive entrypoint using [references/project-adapters.md](references/project-adapters.md). Run relevant unit/UI tests and an iOS Simulator smoke test, but do not claim that Simulator proves profile enrollment or OTA installation.
2. Produce a Release archive and an initial Ad Hoc IPA. Confirm the archive bundle ID/build match the intended release and that export uses the correct Apple team.
3. Scaffold the portal from the bundled, tested template:

   ```bash
   python3 "$HOME/.codex/skills/publish-ios-phone-app/scripts/scaffold_installer.py" \
     --output /ABSOLUTE/PATH/installer \
     --app-name "APP_NAME" --app-short-name "APP_SHORT_NAME" \
     --organization "COMPANY_NAME" --bundle-id "BUNDLE_ID" \
     --bundle-version "BUILD_NUMBER" --marketing-version "MARKETING_VERSION" \
     --base-url "https://install.company.example" \
     --archive-path /ABSOLUTE/PATH/App.xcarchive \
     --ipa-path /ABSOLUTE/PATH/App.ipa \
     --export-options-path /ABSOLUTE/PATH/ExportOptions-AdHoc.plist \
     --icon-57 /ABSOLUTE/PATH/icon-57.png \
     --icon-512 /ABSOLUTE/PATH/icon-512.png
   ```

4. Fill the generated `.env` with App Store Connect API values. Configure one supported CMS-signing mode for the `.mobileconfig`: either a keychain identity in `profile_sign_identity`, or the certificate, chain, and private-key paths in `config.json`. Never commit `.env`, `.p8`, private keys, enrollment databases, or `installer-link.txt`.
5. Run `scripts/setup.sh` and `scripts/check.sh`. Deploy the service behind a trusted HTTPS certificate at the exact `base_url`; keep the signing/export worker on macOS with Xcode and the distribution certificate available. Read [references/deployment-and-verification.md](references/deployment-and-verification.md) before exposing the origin.
6. Verify the entire state machine: invite token → customer/device name → explicit consent → signed Profile Service download → CMS/challenge validation → encrypted UDID storage → App Store Connect device registration → serialized Ad Hoc re-export → HTTPS manifest/IPA → one-click `itms-services` install.
7. Run the release validator, first locally and then against the public manifest/IPA:

   ```bash
   python3 "$HOME/.codex/skills/publish-ios-phone-app/scripts/validate_release.py" \
     --ipa /ABSOLUTE/PATH/App.ipa \
     --manifest https://install.company.example/manifest.plist \
     --expected-bundle-id BUNDLE_ID --expected-build BUILD_NUMBER \
     --expected-udid DEVICE_UDID \
     --public-ipa-url https://install.company.example/downloads/App.ipa
   ```

8. Complete one end-to-end test on a real, permitted iPhone before sharing the link. Confirm LINE users receive Safari handoff instructions, the registration callback succeeds, the new device is embedded in the provisioning profile, the install button disables after one click, the home-screen download starts, the app launches, and critical app flows work.

## Invariants

- Request only `UDID`, `PRODUCT`, and `VERSION`; verify the signed CMS chain and per-enrollment challenge before accepting them.
- Require a random portal access token and a separate random, expiring enrollment token. Rate-limit creation; never expose an unrestricted `/start` endpoint.
- Encrypt raw UDIDs at rest, log only a truncated hash, serialize device registration/re-export, and delete enrollment data at the disclosed retention deadline.
- Manifest bundle ID/build must equal the embedded app metadata. The IPA URL must be HTTPS and served as `application/octet-stream`; the manifest must use a valid plist MIME type. Link through `itms-services`, not directly to the IPA.
- A newly registered device is installable only after the exported IPA's embedded Ad Hoc provisioning profile includes that UDID. Never mark an enrollment ready merely because the API registration call succeeded.
- Increment `CFBundleVersion` for updates and replace public artifacts atomically. Keep the previous verified IPA/manifest for rollback.
- LINE-to-Safari handoff is guided, not guaranteed by iOS; retain copy-link instructions. OTA/profile success must be tested on a real iPhone.

## Deliverables

Return the customer link, deployment location, app/bundle/build identifiers, registered-device count versus quota, SHA-256 of the public IPA, verification results, data-retention setting, rollback location, and any remaining external action that still requires the user's confirmation.
