# Acova Timerprog Bluetooth for Home Assistant

Local Bluetooth LE control of **Acova electric towel radiators with the "Timerprog Bluetooth"
controller** (Zehnder group), the ones driven by the official **AcovaControl** app.
The controller advertises as `TEMPO 3`.

No cloud, no app, no extra hardware: Home Assistant talks to the radiator through its own
Bluetooth adapter (or an ESPHome Bluetooth proxy).

> Unofficial project, not affiliated with Acova or Zehnder.
> The protocol was documented from the public AcovaControl app for interoperability purposes.

## Features

| Entity | Description |
|---|---|
| `climate` | `heat` / `off` (off = frost protection, 7 °C), presets **comfort** and **eco**, comfort setpoint (0.5 °C steps) |
| `climate` presets (read-only) | **2h boost**, **auto** and **program** when they come from the radiator itself |
| `binary_sensor` 2h boost | on while the front-panel 2h boost runs |
| `binary_sensor` open window detection | whether the feature is enabled (diagnostic) |

Options:

- **Who has the last word**
  - *Radiator front panel* (default): Home Assistant shows the real state and never overrides
    a change made on the radiator.
  - *Home Assistant*: at the next poll, Home Assistant re-applies its last mode if it was changed
    on the radiator. A running 2h boost is always respected.
- **Polling interval**: 60–3600 s (default 300). Each poll opens a short BLE connection
  (a few seconds); the connection is never kept open, so the phone app still works.

Not available over Bluetooth: room temperature, heating state, front-panel dial position.
Use an external thermometer if you need `current_temperature` (e.g. with a template or
[Versatile Thermostat](https://github.com/jmcollin78/versatile_thermostat)).

## Tested hardware

| Radiator | Controller | Firmware |
|---|---|---|
| Acova Atoll Spa TSL-050-050-TF (500 W, 2022) | Timerprog Bluetooth | product 2.97, BLE 7.35 |

Other Acova / Zehnder radiators using AcovaControl and advertising `TEMPO 3` should work.
Reports welcome. "Acova Connect" products use another protocol and are not supported.

Requires Home Assistant 2024.12 or later (tested on 2025.11.3), with a working Bluetooth adapter
or ESPHome Bluetooth proxy within good range of the radiator (around −75 dBm or better).

## Installation

### HACS
1. HACS → ⋮ → *Custom repositories* → add `https://github.com/nirae/ha-acova-timerprog`,
   category *Integration*.
2. Install **Acova Timerprog Bluetooth**, then restart Home Assistant.

### Manual
Copy `custom_components/acova_timerprog` into your `config/custom_components/` and restart.

## Pairing (required)

The controller only executes commands from a **bonded** client. Without bonding it accepts the
connection but ignores requests.

1. Long press the **2h** button on the radiator: this opens the pairing window.
2. Right away, pair from the Home Assistant host (Home Assistant OS: use the SSH add-on with
   host D-Bus access, or any shell on the host):

   ```
   bluetoothctl
   agent NoInputNoOutput
   default-agent
   scan le
   pair XX:XX:XX:XX:XX:XX      # the TEMPO 3 address
   trust XX:XX:XX:XX:XX:XX
   disconnect XX:XX:XX:XX:XX:XX
   scan off
   ```

   If it times out, start `pair` first and press 2h while it retries, or move the adapter closer.
3. The radiator is discovered automatically (*Settings → Devices & services*). The setup form
   performs a test read and reports `not paired` if bonding is missing.

Several devices can be bonded at the same time: the phone app keeps working.

## Good to know

- **The power button (⏻) and the "standby" mode switch Bluetooth off.** The integration never
  sends standby; its `off` is frost protection. When the radiator is switched off with ⏻, the
  entities become unavailable until it is switched back on (it then restarts in *auto*).
- In frost protection the radiator forces 7 °C. The comfort setpoint is remembered by the
  integration and sent again when heating resumes.
- In eco mode the radiator reports registers that differ from what was written. Like the app,
  the integration keeps the comfort setpoint and shows eco = comfort − 3.5 °C.
- Using AcovaControl after Home Assistant re-sends the app's own saved configuration and
  overrides Home Assistant's settings.

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md).

## License

[MIT](LICENSE)
