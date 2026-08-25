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

## Release checklist

### Local

- App tests and iOS Simulator smoke test pass.
- Release archive succeeds; `CFBundleIdentifier`, `CFBundleShortVersionString`, and `CFBundleVersion` are correct.
- Portal unit tests and Python compilation pass.
- Generated profile is CMS-signed and requests only `UDID`, `PRODUCT`, `VERSION`.
- `validate_release.py` reports valid bundle/build, codesign, Ad Hoc provision, and expected UDID inclusion.

### Public

- HTTPS certificate and hostname validate from an external network.
- `HEAD`/`GET` for manifest, IPA, and icons return correct status, MIME, and nonzero content.
- Public IPA SHA-256 equals the locally verified release.
- Entry without `access` is rejected; valid invite token works; rate limit works.
- LINE user-agent renders Safari/copy-link guidance and does not expose registration actions inside LINE.
- Install button stores build-and-enrollment-specific clicked state, disables immediately, and says to return to the home screen.

### Real iPhone

Simulator can verify web layout and normal app UI only. A permitted physical iPhone must verify profile download, Settings installation, Apple CMS callback, UDID registration, provisioning inclusion, `itms-services` confirmation, home-screen download, launch, login/logout, navigation, camera/QR, printing, and any hardware-dependent flows.

Stop after the first unexplained Apple registration/export failure, preserve diagnostic logs without raw secrets, repair the cause, and rerun the gates. Do not loop external registrations or exports indefinitely.
