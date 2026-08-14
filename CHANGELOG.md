# Changelog

## v0.3.16

- Replaced seed-shade setup with controller-address-only setup and automatic shade discovery.
- Added collision-safe v1 config-entry migration while preserving legacy entity unique IDs.
- Kept all multi-shade controller traffic serialized through one shared lock.
- Normalized expected closed-aiohttp-session shutdown failures into the normal communication path.
- Hardened discovery against malformed, duplicate, and individually unavailable shade records.
- Added Zigbee NWK-address re-resolution using the existing permanent native identifier lookup.
- Enabled newly discovered shade entities by default without changing existing registry choices.
- Added privacy-redacted diagnostics and expanded Ruff, pytest, and compile CI coverage.

## v0.3.15

- Added a 60-second time-based communication-failure grace period so established shades retain last-known state through brief misses while sustained outages still become unavailable.

## v0.3.14

- Treated known temporary position responses, including `file empty` and incomplete wired position packets, as transient.
- Reduced idle polling to 20 seconds while retaining 1-second movement polling.

## v0.3.13

- Changed wired rolling-speed updates to send only the `13 0E` speed packet, preserving the motor's configured Standard/Reversed direction.
