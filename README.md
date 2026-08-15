# Screen Innovations TRO.Y 2 (Troy) for Home Assistant

**Direct local control of Screen Innovations TRO.Y shades from Home Assistant — no Bond Bridge Pro required for this integration.**

This custom integration connects Home Assistant directly to a Screen Innovations TRO.Y controller on your local network. TRO.Y remains the controller and source of truth, while Home Assistant provides native cover entities, automation support, percentage positioning, state reconciliation, and wired-motor speed controls.

Because Home Assistant reads shade position from TRO.Y, the integration can reconcile state after a shade is moved by another TRO.Y-connected control instead of relying only on commands previously sent by Home Assistant.

> [!IMPORTANT]
> This is an independent community project. It is not affiliated with or endorsed by Screen Innovations, Bond, or Home Assistant.

## Why this integration exists

If you already have TRO.Y, Home Assistant can talk to it directly. That means you can avoid adding another bridge solely to expose TRO.Y-controlled shades to Home Assistant.

The architecture is intentionally simple:

```text
Home Assistant
      |
      | local network
      v
    TRO.Y 2
   /   |   \
RS485 Zigbee RTS*
 shades shades shades
```

Instead of treating Home Assistant as the only source of state, this integration periodically asks TRO.Y for the shade position. That matters when shades are operated from remotes, wall controls, TRO.Y itself, or other systems connected to the controller.

## Highlights

- **Direct TRO.Y connection** — communicates with the TRO.Y controller over your local network.
- **No additional bridge required** — Home Assistant talks directly to TRO.Y for this integration.
- **Controller-sourced state** — Home Assistant reconciles shade position from TRO.Y rather than simply assuming the last command succeeded.
- **Local control** — normal shade control does not depend on a cloud service.
- **Automatic shade discovery** — all shades returned by the TRO.Y controller are discovered after setup.
- **Native Home Assistant covers** — open, close, stop, and percentage positioning.
- **Fast movement tracking** — position polling accelerates while a Home Assistant-commanded movement is active.
- **Low-overhead idle polling** — idle shade state is reconciled every 20 seconds to reduce unnecessary controller traffic.
- **Fair controller scheduling** — one shared runtime prioritizes commands and moving shades while continuing to refresh idle shades.
- **Transient-response resilience** — temporary TRO.Y position responses such as `file empty` are handled without unnecessarily dropping an otherwise healthy shade.
- **Wired-motor speed control** — compatible RS485 shades can store independent up, down, and slow speed settings.
- **Direction-safe speed updates** — changing wired motor speeds does not modify the motor's persistent direction setting.

## Why controller-sourced state matters

A shade system is often controlled from more than one place. Home Assistant may issue one command, while another command later comes from a wall station, handheld remote, TRO.Y interface, or another integration.

This integration periodically reconciles with TRO.Y so Home Assistant can follow the state reported by the controller. That makes automations, dashboards, and HomeKit exposure much more useful than an architecture that only remembers what Home Assistant last asked the shade to do.

## Supported functionality

| Capability | Status |
| --- | --- |
| Local TRO.Y connection | Supported |
| Automatic shade discovery | Supported |
| Open / close / stop | Supported |
| Percentage positioning | Supported |
| Controller-reported position reconciliation | Supported where TRO.Y reports position |
| Faster polling during movement | Supported |
| Wired RS485 motor speed settings | Supported |
| Home Assistant automations and scripts | Supported |
| HomeKit exposure through Home Assistant | Supported through Home Assistant's HomeKit Bridge |

## Shade compatibility

### RS485 / wired shades

**Tested.** Direct control, percentage positioning, position feedback, and supported wired-motor speed settings have been field-tested.

### Zigbee shades

**Tested.** Two-way shade control and position/state feedback through TRO.Y have been field-tested.

### RTS shades

**Basic control is expected, but RTS has not yet been formally field-tested with this integration.** RTS is a one-way RF technology, so position feedback and synchronization may differ from RS485 and Zigbee shades. Users with TRO.Y-connected RTS shades are encouraged to report results through GitHub Issues.

## Target release

**Version 0.3.17** introduces controller-level runtime coordination and corrected outage detection.

The current implementation includes:

- direct local TRO.Y communication
- automatic controller-wide shade discovery
- open, close, stop, and position commands
- controller-sourced position polling
- 20-second idle reconciliation
- 1-second movement polling while a commanded movement is active
- one controller-level scheduler with serialized controller traffic
- fair, bounded polling without stale-request backlog
- failure episodes measured from actual failed requests
- separate controller-wide and per-shade health state
- resilient startup discovery
- transient position-response handling
- wired Up / Down / Slow motor speed configuration
- direction-safe wired speed updates
- controller-only setup with automatic shade discovery
- collision-safe migration from v1 seed-shade entries
- automatic Zigbee node-address re-resolution after a rejoin
- privacy-redacted Home Assistant diagnostics

Setup asks only for the TRO.Y controller IP address or hostname. The integration validates the controller and automatically discovers all shades it reports. Because the existing TRO.Y responses used by this integration do not expose a reliable controller serial number or permanent ID, the normalized controller address is used as the config-entry identity. A DHCP reservation or static IP is recommended.

## Installation with HACS

Until this repository is accepted into a default HACS catalog:

1. Open **HACS** in Home Assistant.
2. Add this repository as a custom repository with category **Integration**.
3. Search for **Troy** and install **Screen Innovations TRO.Y 2 (Troy)**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**.
6. Search for **Troy** and select **Screen Innovations TRO.Y 2 (Troy)**.
7. Enter the TRO.Y controller IP address or hostname. Home Assistant discovers and adds all reported shades automatically under **TRO.Y 2 Shade Controller**.

## Manual installation

Copy:

```text
custom_components/troy2
```

into:

```text
/config/custom_components/troy2
```

Restart Home Assistant, then add **Screen Innovations TRO.Y 2 (Troy)** from **Settings → Devices & services** and enter the controller IP address or hostname.

## Wired shade speed action

The `troy2.set_wired_speeds` action sets the three persistent rolling-speed values stored by a compatible wired motor:

- Up speed
- Down speed
- Slow speed

All three values are required and must be between **10 and 25**.

```yaml
action: troy2.set_wired_speeds
target:
  entity_id: cover.example_shade
data:
  up_speed: 25
  down_speed: 10
  slow_speed: 15
```

Speed updates are sent independently of motor direction, so an existing Standard or Reversed motor orientation is preserved.

Do not target a wireless shade; Home Assistant will reject the action.

## HomeKit and voice assistants

Because the shades are exposed as normal Home Assistant `cover` entities, they can participate in the rest of the Home Assistant ecosystem, including dashboards, scripts, automations, scenes, and Home Assistant's HomeKit Bridge.

This repository does not implement a separate HomeKit or voice-assistant protocol. Those capabilities are provided by Home Assistant itself.

## Reliability design

TRO.Y occasionally returns temporary position responses without usable shade data. The integration treats known transient position conditions separately from true controller failures so a brief controller timing condition does not unnecessarily mark a healthy shade unavailable.

Established shades retain their last known position after an isolated communication failure. The outage clock starts when an actual request fails; poll lateness or the age of an earlier successful poll is not counted as failure time. Repeated actual failures spanning approximately 60 seconds confirm an outage, while any successful request clears the current failure episode immediately.

One controller-level runtime owns idle polls, faster movement polls, and commands. Poll work is represented by one due time per shade rather than an accumulating queue. Commands normally run first, while oldest-due poll selection and a command-burst limit keep moving and idle shades from starving one another. Every operation also shares one asynchronous controller lock, so requests cannot interleave on TRO.Y.

Health is tracked independently per shade and at the controller level. Repeated failures from one shade do not make successful sibling shades unavailable. Continuous transport failures across multiple shades can confirm controller or network loss, with clean automatic recovery after the next successful communication.

After a confirmed controller outage, restored controller reachability does not immediately expose stale sibling state. Each shade remains unavailable until its own position is verified; the scheduler makes unverified shades immediately due for a fair recovery sweep. Repeatedly timing-out shades use bounded poll backoff so they continue receiving recovery attempts without consuming a disproportionate share of controller capacity. The proven 10-second HTTP timeout is unchanged.

Initial position acquisition also runs through the controller scheduler after discovery. Setup therefore does not wait through a sequential timeout for every unavailable shade; entities appear with normal unavailable/unknown state until their first successful position report.

Wireless shades retain identity from their permanent native identifier. A current Zigbee network address is refreshed only after a missing-address or explicit address-like rejection; a timeout, transient `file empty`, or malformed response does not automatically add lookup and retry traffic.

Idle polling is intentionally slower than active movement polling:

- **Idle:** every 20 seconds
- **During Home Assistant-commanded movement:** every 1 second

This keeps state reasonably fresh while avoiding constant unnecessary traffic to the controller.

Home Assistant diagnostics report integration version, scheduler state, aggregate request counts and latency, poll lateness, controller health, and privacy-safe per-shade failure and movement state. A stable entry-scoped anonymous token allows the same shade to be correlated across repeated diagnostic captures. Controller addresses, shade names, node addresses, and permanent native identifiers are omitted.

## Privacy

Communication is local between Home Assistant and the TRO.Y controller during normal shade operation. This repository contains no household-specific controller addresses, shade names, credentials, or node IDs.

## Project status and contributions

This integration was developed against real TRO.Y hardware and is actively field-tested with RS485 and Zigbee shades.

Bug reports, compatibility reports, and reproducible protocol findings are welcome. If you have TRO.Y-connected RTS shades or a shade configuration not represented above, your test results can help improve compatibility for everyone.

When opening an issue, please include:

- Home Assistant version
- TRO.Y integration version
- shade technology if known: RS485, Zigbee, or RTS
- concise reproduction steps
- redacted relevant logs

## Brand artwork

The integration icon is original project artwork and is not an official Screen Innovations logo.

## License

MIT
