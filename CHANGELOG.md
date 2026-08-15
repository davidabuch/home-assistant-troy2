# Changelog

## v0.3.17

- Coordinated all shade polling and commands through one controller-level runtime.
- Added fair, bounded multi-shade scheduling with command priority and faster movement observation.
- Corrected availability so outage duration begins with the first actual failed request, not the age of a previous successful poll.
- Distinguished controller-wide communication loss from an individual shade failure and preserved healthy sibling shades.
- Kept shades unverified after a controller outage until each shade reports successfully, with a prompt recovery sweep.
- Moved initial position acquisition into the bounded scheduler and backed off repeatedly failing shades without changing the 10-second request timeout.
- Improved timeout, HTTP, malformed-response, Zigbee-address, and orderly-shutdown diagnostics.
- Added stable privacy-safe anonymous shade correlation to diagnostics.

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
