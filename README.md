# Screen Innovations TRO.Y 2 for Home Assistant

Custom Home Assistant integration for locally controlling shades connected to a Screen Innovations TRO.Y 2 controller.

> [!IMPORTANT]
> This is an independent community project. It is not affiliated with or endorsed by Screen Innovations or Home Assistant.

## Current status

Version 0.3.10 is the current field-tested version. It supports local shade discovery, position polling, open/close/stop/position commands, wired-motor speed control, serialized controller traffic, faster polling while a shade is moving, and resilient startup discovery.

The integration currently uses a legacy-compatible setup flow that asks for the controller IP address, one wired shade node ID, and a friendly name. After setup, all shades returned by that controller are discovered. A controller-first setup flow is planned for v0.4.0.

## Installation with HACS

Until this repository is accepted into a default HACS catalog:

1. Open HACS in Home Assistant.
2. Add this repository as a custom repository with category **Integration**.
3. Search for **Screen Innovations TRO.Y 2** and install it.
4. Restart Home Assistant.
5. Go to **Settings → Devices & services → Add integration**.
6. Search for **Screen Innovations TRO.Y 2**.

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
