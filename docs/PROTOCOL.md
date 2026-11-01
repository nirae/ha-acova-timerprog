# Acova Timerprog Bluetooth protocol

Documented from the behaviour of the AcovaControl app (Android package `fr.acova.toumiprogram`)
and validated against a Timerprog Bluetooth controller (product firmware 2.97, BLE 7.35).

## Advertising

- Local name `TEMPO 3`, random static address, no manufacturer or service data.
- Only advertises while powered on and not in standby. No advertising while a client is connected.

## GATT

| Service | Characteristic | Properties | Role |
|---|---|---|---|
| `03366e80-cf3a-11e1-9ab4-0002a5d5c51b` | `350a1b80-cf4b-11e1-ac36-0002a5d5c51b` (CMD) | write | short commands |
| `03366e80-cf3a-11e1-9ab5-0002a5d5c51b` | `350a1b80-cf4b-11e1-ac37-0002a5d5c51b` (BUF) | read, write, notify | data buffer (72 bytes) |

Device Name and Appearance are writable: leave them alone.

## Security

LE bonding is required (Just Works). The pairing window opens with a long press on the 2h button.
An unbonded client can connect and write, but the controller ignores requests and the buffer keeps
its previous content.

## Session

The app connects, enables notifications on BUF, performs its requests, waits ~3 s, disables
notifications and disconnects. It never keeps the connection open.

### Read an object

1. Write `[0x00, obj, data]` to CMD.
2. Notification on BUF: `[obj, data, len, value…]`.
3. If `len > 17`, the notification is truncated: read BUF to get the full value.

### Write an object

1. Write a 30-byte frame `[obj, data, len, value…, 0x00…]` to BUF.
2. Read BUF until it echoes `[obj, data, …]`.
3. Write `[0x01, obj, data]` to CMD (commit).
4. Read BUF until it returns `[0x00, 0x00, …]`.

## Objects

| obj | data | Name | Format |
|---|---|---|---|
| 100 | 1 / 2 | product firmware minor / major | u8 |
| 100 | 3 / 4 | BLE firmware minor / major | u8 |
| 113 | 1 | open window status | bit0 = enabled |
| 113 | 2 | open window control | bit0 = enable, bit1 = disable |
| 115 | 1 | calendar status | u8 |
| 115 | 2 | calendar control | bit0 lock, bit1 unlock, bit2 set new clock |
| 115 | 3 | day of week | 1 = Monday … 7 = Sunday (2 bytes) |
| 115 | 7 / 8 / 9 | hour / minute / second | 2 bytes |
| 116 | 3 | mode | see below |
| 116 | 4 | eco setpoint | °C × 2 |
| 116 | 5 | comfort setpoint | °C × 2 |
| 116 | 6 | temperature offset | int8, °C × 10 |
| 117 | 1 | week program status | u8 |
| 117 | 3 … 9 | week program, Monday … Sunday | 20 bytes: `[mode, 0, (mode, hour × 4) × n]` |

### Modes (116/3)

| Value | Meaning | Notes |
|---|---|---|
| 1 | standby | **switches Bluetooth off**; only the ⏻ button wakes the radiator |
| 2 | frost protection | radiator forces comfort = 7 °C, eco = 3.5 °C |
| 3 | night / eco | |
| 4 | day / comfort | |
| 8 | user program | |
| 9 | auto | state after power-on with the ⏻ button |
| 13 | 2h boost | observed while the front-panel boost runs; never written by the app |

When the app saves settings, it writes in this order: open window control, mode, eco, comfort,
offset, clock (control = lock, hour, minute, second, day, control = set new clock),
then the seven days of the week program.
