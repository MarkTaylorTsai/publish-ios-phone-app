# Deployment and verification

## Architecture

Keep the HTTP service and Xcode signing worker on a protected macOS host unless the signing operation is deliberately split into a separate queue/worker. The generated service provides:

1. `/?access=...` — protected branded entry page;
2. `/start` — rate-limited creation of a random enrollment URL;
3. `/e/TOKEN` — customer name, consent, instructions, and status;
4. `/e/TOKEN/profile.mobileconfig` — signed Profile Service payload requesting only UDID/product/iOS version;
5. `/profile/TOKEN` — CMS-verified Apple device callback with challenge matching;
6. App Store Connect registration and serialized `xcodebuild -exportArchive`;
7. `/manifest.plist` and `/downloads/APP.ipa` — OTA release artifacts.

The Profile Service contract follows Apple's archived OTA profile documentation: [Over-the-Air Profile Delivery and Configuration](https://developer.apple.com/library/archive/documentation/NetworkingInternet/Conceptual/iPhoneOTAConfiguration/profile-service/profile-service.html).

Apple's deployment guide describes HTTPS manifest installation using `itms-services://?action=download-manifest&url=...` and the manifest/IPA MIME requirements: [Distribute proprietary in-house apps](https://support.apple.com/guide/deployment/depce7cefc4d/web). Although that page addresses in-house apps, the OTA manifest transport requirements also apply to an Ad Hoc IPA; the signing eligibility remains Ad Hoc and device-specific.

## HTTPS and DNS

- Point `install.company.example` to the chosen reverse proxy or tunnel only after the user authorizes the DNS mutation.
- Use a publicly trusted TLS certificate. The certificate name must match the exact `base_url` host.
- Terminate TLS at a reverse proxy or authenticated tunnel and proxy only to the loopback listener. Do not expose the Python listener directly.
- Restrict the origin so the tunnel/proxy is the only public path; enable request/body size limits and rate limits at both layers.
- Serve the manifest as `application/xml` or another valid plist type and the IPA as `application/octet-stream`.
- Health checks must not expose configuration, enrollment state, secrets, customer names, or UDIDs.

## Secrets and retention

- `.env`, private keys, API keys, `installer-link.txt`, `data/`, `logs/`, and exported credentials must be ignored by version control and mode `0600` where applicable.
- Keep raw UDIDs encrypted. Logs may contain only a short SHA-256 prefix for correlation.
- Schedule deletion of expired enrollments and associated profiles according to `data_retention_days`; this is an operational job, not only page text.
- Rotate `INSTALL_PORTAL_TOKEN` to revoke the shared entry link. Enrollment URLs remain separate random tokens and expire.
- Back up the last verified IPA/manifest and configuration without copying active secrets into an ordinary repository snapshot.

## Background export gate

The `.mobileconfig` CMS signer and the app's distribution signer are different. A signed profile, an existing IPA, or HTTP 200 from every read-only ASC preflight endpoint does not prove the deployed service can re-export an IPA after enrollment.

Set `export_authentication` in `config.json` (or scaffold with `--export-authentication`):

- `api-key` (default): passes the three `-authenticationKey...` flags to `xcodebuild`. Verify this identity can perform the chosen local or cloud-managed distribution signing, not just read provisioning resources.
- `xcode-account` (explicit opt-in): omits those flags and uses the signed-in Xcode account of the service's macOS user, retaining `-allowProvisioningUpdates`. Verify that account belongs to the archive/ExportOptions team and has the necessary distribution/cloud-signing access. The team API key still registers devices. This is not an automatic fallback after API-key export fails.

Before inviting a customer, run one staging export with the real archive, ExportOptions, and chosen authentication from the **same macOS user and background service context** used in production. Validate the candidate's bundle/build, signature, Ad Hoc profile, and an already permitted device's inclusion without registering a synthetic UDID. Keep production artifacts unchanged until validation passes. Interactive-shell success does not prove LaunchAgent/keychain/session access. Put the probe script, archive, and output in service-readable deployment storage (for example, the application's private Application Support directory); macOS privacy controls may deny a background process access to a script under Documents even when a terminal can read it. Fix the deployment location/access rather than misdiagnosing that OS error as Apple signing failure. Preserve a redacted result identifying the authentication mode and background context, never raw key paths, tokens, device names, or UDIDs.

For a real enrollment failure, inspect whether `registered_at` is populated and whether the failing stage is registration or export. Preserve the consent and encrypted callback data, repair the failing export identity or environment, then retry that same enrollment once. Stop if the error recurs; do not create duplicate device records or loop credential changes. Keep the last verified IPA intact on every failed export.

Apple describes both authenticated Xcode command-line paths in [Distribute apps in Xcode with cloud signing](https://developer.apple.com/videos/play/wwdc2021/10204/) and the distinction between local and cloud-managed identities in [Cloud-managed certificates](https://developer.apple.com/help/account/certificates/cloud-managed-certificates/).

## Release checklist

### Local

- App tests and iOS Simulator smoke test pass.
- Release archive succeeds; `CFBundleIdentifier`, `CFBundleShortVersionString`, and `CFBundleVersion` are correct.
- Portal unit tests and Python compilation pass.
- Generated profile is CMS-signed and requests only `UDID`, `PRODUCT`, `VERSION`.
- Real staging export passes from the deployed background-service context with the explicitly selected authentication mode; read-only API checks are recorded separately.
- `validate_release.py` reports valid bundle/build, codesign, Ad Hoc provision, and expected UDID inclusion.

### Public

- HTTPS certificate and hostname validate from an external network.
- `HEAD`/`GET` for manifest, IPA, and icons return correct status, MIME, and nonzero content.
- Public IPA SHA-256 equals the locally verified release.
- Entry without `access` is rejected; valid invite token works; rate limit works.
- LINE user-agent renders Safari/copy-link guidance and does not expose registration actions inside LINE.
- Install button stores build-and-enrollment-specific clicked state, disables immediately, and says to return to the home screen.
- The first install click reveals the complete Developer Mode sequence and the missing-switch Mac/Xcode pairing guidance; revisiting the same build/enrollment restores the revealed state.

### Real iPhone

Simulator can verify web layout and normal app UI only. A permitted physical iPhone must verify profile download, Settings installation, Apple CMS callback, UDID registration, provisioning inclusion, `itms-services` confirmation, home-screen download, Developer Mode enablement and restart, launch, login/logout, navigation, camera/QR, printing, and any hardware-dependent flows.

Stop after the first unexplained Apple registration/export failure, preserve diagnostic logs without raw secrets, repair the cause, and rerun the gates. Do not loop external registrations or exports indefinitely.
