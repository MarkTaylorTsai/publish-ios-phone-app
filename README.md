# publish-ios-phone-app

A vendor-neutral agent skill that turns an existing iOS project into a branded, customer-consent Ad Hoc installation portal such as `https://install.company.example`.

Customers can:

1. open the protected installation link in iPhone Safari;
2. enter a customer/device name and explicitly consent;
3. install a minimal profile that returns only UDID, product model, and iOS version;
4. wait while the device is registered and the archive is re-exported;
5. install the verified IPA over the air.

The template includes App Store Connect device registration, encrypted UDID storage, signed Profile Service payloads, CMS/challenge validation, serialized Xcode export, OTA manifest generation, LINE-to-Safari guidance, one-click install state, retention cleanup, configurable link-creation rate limits (default: 100 requests per source IP per 10 minutes), and release validation.

## Use with any agent

```bash
git clone https://github.com/MarkTaylorTsai/publish-ios-phone-app.git \
  /ABSOLUTE/PATH/TO/publish-ios-phone-app
```

Point the agent's skill loader at that directory, or ask the agent to read `SKILL.md` directly. The workflow does not depend on a vendor-specific runtime; the agent only needs filesystem access, shell execution, HTTPS access, macOS/Xcode, and the required Apple credentials.

Agents that support named skills can invoke:

```text
publish-ios-phone-app: Publish this existing iOS project through a branded customer-consent installation link.
```

## Requirements

- macOS with Xcode and the project's working iOS archive flow
- Apple Developer team and an Ad Hoc-compatible distribution certificate
- App Store Connect API issuer ID, key ID, and private `.p8` key
- a trusted HTTPS hostname such as `install.company.example`
- a permitted physical iPhone for final profile and OTA verification

Ad Hoc distribution is device-limited. Check Apple's current [device limits](https://developer.apple.com/help/account/devices/devices-overview/) before committing to an audience size.

## Security

Generated `.env`, `.p8`, private keys, raw UDIDs, customer names, databases, and `installer-link.txt` are intentionally excluded from version control. The shared entry URL contains a revocable random access token, while every enrollment receives a separate expiring token.

Read [`SKILL.md`](SKILL.md) for the full workflow and invariants.
