# Project adapters

Read only the section matching the repository. Derive real paths and schemes from the project; placeholders below are not commands to run unchanged.

## Native Xcode / Swift / Objective-C

Discover shared schemes before archiving:

```bash
xcodebuild -list -json -workspace /ABSOLUTE/PATH/App.xcworkspace
# or
xcodebuild -list -json -project /ABSOLUTE/PATH/App.xcodeproj
```

Run the project's tests, then create a generic iOS device archive:

```bash
xcodebuild archive \
  -workspace /ABSOLUTE/PATH/App.xcworkspace \
  -scheme APP_SCHEME -configuration Release \
  -destination 'generic/platform=iOS' \
  -archivePath /ABSOLUTE/PATH/App.xcarchive \
  -allowProvisioningUpdates
```

Export with an Ad Hoc/release-testing options plist accepted by the installed Xcode. The bundled `ExportOptions-AdHoc.plist.example` uses `method=release-testing`, which is accepted by current Xcode versions; inspect `xcodebuild -help` or generate an export plist through Xcode when the local version differs.

## React Native / Expo prebuild

Do not distribute a development server shell. Produce the native iOS project first, install CocoaPods if the repository requires it, then archive the resulting `.xcworkspace` using the native workflow. Keep runtime API URLs and production entitlements aligned with the existing release configuration.

## Flutter

Run the repository's Flutter tests and produce an iOS archive/IPA with its configured flavor and export options. If Flutter emits an `.xcarchive`, feed that archive to the portal's re-export worker; otherwise archive `ios/Runner.xcworkspace` with the correct scheme. Confirm the bundle/build embedded in the IPA instead of relying only on `pubspec.yaml`.

## Cross-project checks

- Preserve extensions, App Groups, keychain groups, push notification, associated-domain, and background-mode entitlements during re-export.
- The archive and `ExportOptions` team must refer to the same Apple Developer team.
- `CFBundleVersion` must increase for every customer update. Marketing version may remain unchanged when only the build changes.
- Do not mark the portal ready from an old initial IPA after registering a new device; re-export and validate the newly embedded provisioning profile first.
- Keep application bugs and distribution bugs separate: Simulator/UI tests validate app behavior, while a real registered iPhone validates signing and OTA installation.
