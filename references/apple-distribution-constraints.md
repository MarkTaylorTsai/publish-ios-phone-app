# Apple distribution constraints

Use this reference before selecting or provisioning the distribution method. Re-check the linked Apple pages at execution time because portal roles, quotas, and Xcode export labels can change.

## Ad Hoc fit

Ad Hoc distribution is appropriate for a finite list of registered devices. Apple currently permits up to 100 registered devices per product family per membership year. Disabling a device does not restore its slot during the same membership year; unused slots become available only when the membership resets. Count existing devices before promising capacity.

- Apple: [Devices overview](https://developer.apple.com/help/account/devices/devices-overview/)
- Apple: [Create an Ad Hoc provisioning profile](https://developer.apple.com/help/account/provisioning-profiles/create-an-ad-hoc-provisioning-profile)

Creating an Ad Hoc profile requires an explicit App ID, a distribution certificate, and selected registered devices. Apple documents Account Holder or Admin access for creating that profile. Verify the active account's role rather than inferring permission from possession of source code.

## Developer Mode is required

Apple states that every time an `.ipa`-based app runs on an iOS device, Developer Mode must be enabled. The customer-facing installer must therefore reveal these instructions immediately after the install button is clicked:

1. Wait for the app to finish downloading and try to open it once.
2. Open **Settings → Privacy & Security → Developer Mode**.
3. Turn the switch on and tap **Restart**.
4. After restart, unlock the iPhone, tap **Enable**, and enter the device passcode.
5. Reopen the installed app.

Apple also notes that Developer Mode appears in Settings only after pairing has been initiated or the iPhone was previously paired to a Mac. If the switch is missing, instruct the customer to connect the unlocked iPhone to a Mac, tap **Trust**, and open Xcode's **Window → Devices and Simulators** once before checking Settings again.

- Apple: [Distributing your app to registered devices](https://developer.apple.com/documentation/xcode/distributing-your-app-to-registered-devices)
- Apple: [Enabling Developer Mode on a device](https://developer.apple.com/documentation/xcode/enabling-developer-mode-on-a-device)

## Automated registration

The installer template uses the App Store Connect API to look up and register a device, then invokes Xcode to re-export the existing archive so the resulting provisioning profile includes the device.

- Apple: [Get started with the App Store Connect API](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api/)
- Apple API: [Register a new device](https://developer.apple.com/documentation/appstoreconnectapi/post-v1-devices)
- Apple API: [Profiles resource](https://developer.apple.com/documentation/appstoreconnectapi/profiles)

Do not upload or expose App Store Connect `.p8` keys to the web root. Scope and store credentials for the signing worker only.

## When this path does not fit

- Use TestFlight for larger beta groups that can accept TestFlight/App Store Connect review requirements.
- Use App Store or Unlisted distribution for broad customer self-service.
- Use Custom Apps through Apple Business Manager for organization-specific distribution.
- Use Enterprise distribution only when the organization and recipients meet Apple's employee/internal-use program terms; do not substitute it for customer distribution.

Do not silently change the user's chosen path. State the exact Apple constraint and obtain agreement before switching methods.
