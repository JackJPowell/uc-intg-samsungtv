# Samsung TV Integration for Unfolded Circle Remote — Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## Unreleased

---

## v1.3.0 - 2026-03-11

### Added

- **App List select entity.** A new select entity exposes the full list of installed apps on your TV. You can browse and launch any app directly from the Remote interface without navigating the TV's own menus. The current app is reflected immediately after selection and stays in sync when the TV reports a source change via SmartThings.

- **SmartThings multi-worker support.** Samsung limits each registered application to 20 authorized users. This release works around that restriction by distributing users across multiple SmartThings app registrations automatically. A coordinator assigns each new setup to the least-loaded registration, so the limit is effectively multiplied by the number of registrations configured. Existing setups continue to work without any reconfiguration.

- **Per-device SmartThings worker tracking.** Each configured TV now remembers which SmartThings app registration it was set up against. Token refreshes are directed to the correct registration, preventing failures that would otherwise occur if requests were routed to a registration that does not hold the user's tokens.

### Fixed

- Fixed a setup crash that occurred when submitting SmartThings OAuth tokens during discovery-based setup. The response handler called `.lower()` on the `enable_smartthings` field unconditionally, but that field is absent when the token submission screen is active, causing a silent failure that left all SmartThings config values as null.

- Fixed the SmartThings setup screen appearing twice when a TV was added via discovery with the SmartThings checkbox already checked. The integration now proceeds directly to the authorization link screen instead of asking again.

- Fixed SmartThings checkbox handling. The Remote sends checkbox values as the strings `"true"` and `"false"` rather than booleans. The previous code treated the string `"false"` as truthy, which could cause SmartThings setup to trigger unexpectedly.

- Fixed the app list select entity showing a blank current value. The active source reported by SmartThings uses different casing than the app list keys returned by the TV. Matching is now case-insensitive so the displayed selection stays accurate. The selected app is also reflected immediately after launch rather than waiting for the next SmartThings poll.

---

## v1.2.0 - 2026-03-10

---


## v0.1.0 - 2025-01-22

### Added
- First release. Control Yamaha clients on your local network from your Unfolded Circle Remote.
