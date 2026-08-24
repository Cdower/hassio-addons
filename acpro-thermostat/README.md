# Home Assistant Add-on: AC Pro Thermostat

Local control of the AC Pro X/XB-Series smart communicating touchscreen
thermostat — no cloud account, no vendor app.

## About

AC Pro's X-Series and XB-Series air handlers are driven by a wall-mounted
Wi-Fi touchscreen control, sold as **SKU 85432** ("X Series and XB Series Air
Handler Wi-Fi Touchscreen Control OEM", OEM model **WK-010WD1**). Out of the
box the panel is paired to a phone app and talks to the manufacturer's cloud.

It also answers a JSON protocol on the local network, and that is what this
add-on speaks. It finds the panel, pairs with it, and publishes a proper
Home Assistant thermostat over MQTT discovery — so the entity behaves like any
other climate device in automations, dashboards, and voice assistants, and
keeps working when the internet does not.

## What you get

A `climate` entity with:

- Off, heat, cool, auto, dry, and fan-only modes
- Setpoint control in whatever scale the panel is displaying
- Current indoor temperature
- Fan speed, from auto through to high
- Eco, boost, comfort, and sleep presets, where the panel supports them

Plus a temperature `sensor` and a `switch` for each extra function the panel
reports — auxiliary heat, panel backlight, and so on. The add-on asks the
panel what it supports at start-up and only creates entities for the
functions it actually has.

## Installation

1. Add this repository to Home Assistant (Settings → Add-ons → Add-on Store →
   ⋮ → Repositories).
2. Install the **Mosquitto broker** add-on if you have not already, and set up
   the MQTT integration.
3. Install **AC Pro Thermostat**, start it, and check the log.

The thermostat appears under Settings → Devices & Services → MQTT.

Full configuration reference and troubleshooting: [DOCS.md](DOCS.md).

## Support

Open an issue at <https://github.com/Cdower/hassio-addons/issues>.

## License

MIT — see [LICENSE.md](../LICENSE.md).
