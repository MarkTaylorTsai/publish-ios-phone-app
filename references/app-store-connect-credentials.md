# App Store Connect credentials

Read this reference before configuring `.env` or exposing the installer. The device-registration and Ad Hoc re-export path depends on App Store Connect provisioning endpoints, so credentials must be acquired and verified during deployment rather than discovered during the first customer enrollment.

## Required credential type

Use an App Store Connect **team API key** for this workflow. Apple documents that individual API keys cannot use provisioning endpoints. A successful request to an unrelated endpoint therefore does not prove that an individual key can register devices or access bundle IDs and profiles.

If App Store Connect API access has never been enabled for the account, the Account Holder must first request access:

1. Sign in to App Store Connect.
2. Open **Users and Access → Integrations → App Store Connect API**.
3. Select **Request Access**, accept the terms, and submit.

After access is enabled, an Account Holder or Admin creates the team key:

1. Open **Users and Access → Integrations → App Store Connect API → Team Keys**.
2. Select **Generate API Key** or the add button.
3. Give the key a deployment-specific name.
4. Select the least-privileged role that supports the intended registration/export operations. `App Manager` is a practical default for this portal; if the team applies a different role policy, verify the provisioning endpoints below rather than assuming the role is sufficient.
5. Generate the key and immediately download `AuthKey_<KEY_ID>.p8`.

Apple makes the private `.p8` available for download only once and does not retain a recoverable copy. If it has already been downloaded and cannot be located, revoke that key and create a replacement instead of attempting to reconstruct it.

Official references:

- [Get started with the App Store Connect API](https://developer.apple.com/help/app-store-connect/get-started/app-store-connect-api/)
- [Creating API keys for App Store Connect API](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api)
- [Generating tokens for API requests](https://developer.apple.com/documentation/appstoreconnectapi/generating-tokens-for-api-requests)

## Collect the three matching values

Keep these three values from the same active team key:

- `ASC_ISSUER_ID`: the Issuer ID shown on the App Store Connect API page;
- `ASC_KEY_ID`: the Key ID in the active Team Keys table;
- `ASC_PRIVATE_KEY_PATH`: an absolute path to the matching downloaded `.p8` file.

The Key ID and `.p8` must be the same key pair. A Key ID copied from one row with another row's private key produces an authentication failure. Do not use the Apple Team ID as the Issuer ID; they are different values.

Store the `.p8` outside the repository and public web root with mode `0600`. Put only its absolute path in `.env`:

```dotenv
ASC_ISSUER_ID=ISSUER_ID
ASC_KEY_ID=KEY_ID
ASC_PRIVATE_KEY_PATH=/PRIVATE/ABSOLUTE/PATH/AuthKey_KEY_ID.p8
```

Never paste these values into browser-visible pages, logs, evidence reports, screenshots, issue bodies, or chat status updates. If the `.p8` is exposed or lost, revoke it in App Store Connect and replace all three configured values as a set.

## Preflight before public deployment

Run the bundled read-only verifier from the skill repository:

```bash
python3 scripts/verify_asc_credentials.py --env-file /ABSOLUTE/PATH/installer/.env
```

The verifier creates a short-lived JWT and checks read access to Apps, Devices, Bundle IDs, and Profiles without registering a device or changing Apple resources. All four checks must return HTTP 200 before the portal is exposed. Keep the JSON result as secret-free deployment evidence.

The preflight proves authentication and provisioning-resource visibility. It does not consume a device slot and does not prove that the first registration `POST` will succeed. The first mutation must still be triggered only by a consenting, permitted iPhone enrollment; stop after one 403 or unexplained registration error, correct the role/team/key configuration, and retry that enrollment once.

## Troubleshooting

- **401**: check that Issuer ID, Key ID, and `.p8` belong to the same active team key; verify system time and that the key has not been revoked.
- **403 on Devices, Bundle IDs, or Profiles**: confirm this is a team key, not an individual key, and review the key role. Team-key names and roles cannot be edited after creation; revoke and replace the key when its access level is wrong.
- **Apps succeeds but provisioning checks fail**: treat the credential as unsuitable for this workflow. Do not infer readiness from `/v1/apps` alone.
- **Xcode export still prompts or fails after API checks pass**: verify the local distribution certificate, archive team, ExportOptions team ID, and Xcode signing assets separately. App Store Connect API access does not replace the local signing identity.
- **Multiple providers or teams**: verify that the key's team owns the bundle identifier and matches the archive/ExportOptions team. Do not choose a provider only because it is the first account shown in the browser.
