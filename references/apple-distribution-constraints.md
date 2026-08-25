# Apple distribution constraints

Use this reference before selecting or provisioning the distribution method. Re-check the linked Apple pages at execution time because portal roles, quotas, and Xcode export labels can change.

## Ad Hoc fit

Ad Hoc distribution is appropriate for a finite list of registered devices. Apple currently permits up to 100 registered devices per product family per membership year. Disabling a device does not restore its slot during the same membership year; unused slots become available only when the membership resets. Count existing devices before promising capacity.

- Apple: [Devices overview](https://developer.apple.com/help/account/devices/devices-overview/)
- Apple: [Create an Ad Hoc provisioning profile](https://developer.apple.com/help/account/provisioning-profiles/create-an-ad-hoc-provisioning-profile)

Creating an Ad Hoc profile requires an explicit App ID, a distribution certificate, and selected registered devices. Apple documents Account Holder or Admin access for creating that profile. Verify the active account's role rather than inferring permission from possession of source code.

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
