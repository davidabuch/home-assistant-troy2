# Screen Innovations TRO.Y 2 (Troy) for Home Assistant

**Direct local control of Screen Innovations TRO.Y shades from Home Assistant — no Bond Bridge Pro required.**

This integration connects Home Assistant directly to the TRO.Y controller at its local IP address. It does not require a Bond Bridge Pro or another control bridge between Home Assistant and TRO.Y.

Because Home Assistant polls TRO.Y directly for shade position, the TRO.Y controller remains the source of truth. This allows Home Assistant to reconcile shade state after a shade is operated by another TRO.Y-connected control, rather than relying only on commands previously sent by Home Assistant.

> [!IMPORTANT]
> This is an independent community project. It is not affiliated with or endorsed by Screen Innovations, Bond, or Home Assistant.

## Why use this integration?

- **Direct TRO.Y connection** — communicates with the TRO.Y controller over your local network.
- **No Bond Bridge Pro required** — Home Assistant talks directly to TRO.Y without requiring an additional bridge for this integration.
- **Controller-sourced state** — Home Assistant polls TRO.Y for shade position so state can be reconciled when shades are operated elsewhere.
- **Local control** — normal shade control does not depend on a cloud service.
- **Position control** — supports open, close, stop, and percentage positioning.
- **Wired-motor speed control** — supports persistent up, down, and slow speed settings for compatible wired shades.
- **Automatic shade discovery** — shades returned by the TRO.Y controller are discovered after setup.

## Current status

Version 0.3.11 is a presentation and discoverability update to the field-tested 0.3.10 runtime. The integration supports local shade discovery, position polling, open/close/stop/position commands, wired-motor speed control, serialized controller traffic, faster polling while a shade is moving, and resilient startup discovery.

The integration currently uses a legacy-compatible setup flow that asks for the controller IP address, one wired shade node ID, and a friendly name. After setup, all shades returned by that controller are discovered. A controller-first setup flow is planned for v0.4.0.

## Installation with HACS

Until this repository is accepted into a default HACS catalog:

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository with category **Integration**.
3. Search for **Troy** and install **Screen Innovations TRO.Y 2 (Troy)**.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**.
6. Search for **Troy** and select **Screen Innovations TRO.Y 2 (Troy)**.

## Manual installation

Copy `custom_components/troy2` into `/config/custom_components/troy2`, restart Home Assistant, and add the integration from **Settings → Devices & services**.

## Wired shade speed action

The `troy2.set_wired_speeds` action sets the up, down, and slow speed values for a wired shade. All three values are required and must be between 10 and 25.

```yaml
action: troy2.set_wired_speeds
target:
  entity_id: cover.example_shade
data:
  up_speed: 25
  down_speed: 10
  slow_speed: 15
```

Do not target a wireless shade; Home Assistant will reject the action.

## Privacy

Communication is local between Home Assistant and the TRO.Y controller. This repository contains no household-specific controller addresses, shade names, or node IDs.

## Brand artwork

The integration icon is original project artwork and is not an official Screen Innovations logo.

## Support

Use GitHub Issues for reproducible bugs and feature requests. Include the Home Assistant version, integration version, a concise description, and redacted relevant logs.

## License

MIT
