"""Acova Timerprog (TEMPO 3) BLE protocol, as implemented by the AcovaControl app.

No Home Assistant imports here so the module can be exercised with plain bleak.

Two vendor characteristics (CSR-style UUIDs):
- CMD (write): [0, obj, data] = read request, [1, obj, data] = commit staged write.
- BUF (read/write/notify): replies [obj, data, len, payload...]; staged writes are
  30-byte frames with the same layout.
The radiator must be bonded (long press on "2h" during pairing); unbonded clients only
get a stale buffer back.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    close_stale_connections_by_address,
    establish_connection,
)

_LOGGER = logging.getLogger(__name__)

CMD_UUID = "350a1b80-cf4b-11e1-ac36-0002a5d5c51b"
BUF_UUID = "350a1b80-cf4b-11e1-ac37-0002a5d5c51b"

OBJ_OPEN_WINDOW_STATUS = (113, 1)
OBJ_MODE = (116, 3)
OBJ_ECO = (116, 4)
OBJ_COMFORT = (116, 5)
OBJ_OFFSET = (116, 6)
OBJ_FW_MINOR = (100, 1)
OBJ_FW_MAJOR = (100, 2)

# Values of OBJ_MODE. 1-9 come from the app; 13 was observed during a 2h boost.
MODE_STANDBY = 1  # turns BLE off as well: never send it
MODE_FROST = 2
MODE_NIGHT_ECO = 3
MODE_DAY_COMFORT = 4
MODE_USER_PROGRAM = 8
MODE_AUTO = 9
MODE_BOOST = 13

WRITABLE_MODES = {MODE_FROST, MODE_NIGHT_ECO, MODE_DAY_COMFORT}

REPLY_TIMEOUT = 5.0
SESSION_TIMEOUT = 90
DISCONNECT_TIMEOUT = 10
# Must exceed a full session (connect + exchange + disconnect) so a healthy run is
# never pre-empted; past it we assume the previous session is wedged and give up the
# attempt (the coordinator retries) instead of blocking every future poll forever.
LOCK_TIMEOUT = 120
ACK_TRIES = 10
# A session that fails right after connecting (typically ATT "Unlikely Error" 0x0e while
# the bonded link is still being encrypted) succeeds when tried again a moment later.
RETRY_DELAY = 2.0


class TimerprogError(Exception):
    """Communication or protocol error."""


class TimerprogBusyError(TimerprogError):
    """A previous session still holds the radiator (not worth retrying right away)."""


@dataclass(slots=True)
class TimerprogState:
    mode: int
    eco_raw: int
    comfort_raw: int
    offset_raw: int  # signed, 0.1 °C
    open_window_status: int
    firmware: str | None = None

    @property
    def comfort(self) -> float:
        return self.comfort_raw / 2

    @property
    def eco(self) -> float:
        return self.eco_raw / 2


def temp_to_raw(temp: float) -> int:
    return int(round(temp * 2))


def encode_write_frame(obj: tuple[int, int], payload: bytes) -> bytes:
    frame = bytearray(30)
    frame[0], frame[1], frame[2] = obj[0], obj[1], len(payload)
    frame[3 : 3 + len(payload)] = payload
    return bytes(frame)


def decode_reply(obj: tuple[int, int], value: bytes) -> bytes:
    if len(value) < 3 or value[0] != obj[0] or value[1] != obj[1]:
        raise TimerprogError(
            f"unexpected reply for {obj[0]}/{obj[1]}: {value[:4].hex(' ')} "
            "(radiator not paired with this adapter?)"
        )
    return bytes(value[3 : 3 + value[2]])


class TimerprogSession:
    """One connection: subscribe, exchange, unsubscribe, disconnect."""

    def __init__(self, client: BleakClient) -> None:
        self._client = client
        self._queue: asyncio.Queue[bytes] = asyncio.Queue()

    async def start(self) -> None:
        await self._client.start_notify(BUF_UUID, self._on_notify)

    async def stop(self) -> None:
        try:
            if self._client.is_connected:
                await self._client.stop_notify(BUF_UUID)
        except Exception as err:  # noqa: BLE001 - best effort before disconnect
            _LOGGER.debug("stop_notify failed: %s", err)

    def _on_notify(self, _handle, data: bytearray) -> None:
        self._queue.put_nowait(bytes(data))

    async def read(self, obj: tuple[int, int]) -> bytes:
        _LOGGER.debug("read %s/%s", *obj)
        while not self._queue.empty():
            self._queue.get_nowait()
        await self._client.write_gatt_char(CMD_UUID, bytes([0, *obj]), response=True)
        try:
            value = await asyncio.wait_for(self._queue.get(), REPLY_TIMEOUT)
        except asyncio.TimeoutError as err:
            raise TimerprogError(f"no reply for {obj[0]}/{obj[1]}") from err
        if len(value) >= 3 and value[2] > 17:
            value = bytes(await self._client.read_gatt_char(BUF_UUID))
        return decode_reply(obj, value)

    async def _read_until(self, obj: tuple[int, int]) -> bytes:
        value = b""
        for _ in range(ACK_TRIES):
            value = bytes(await self._client.read_gatt_char(BUF_UUID))
            if len(value) >= 2 and value[0] == obj[0] and value[1] == obj[1]:
                return value
            await asyncio.sleep(0.1)
        raise TimerprogError(f"no ack for {obj[0]}/{obj[1]}, got {value[:4].hex(' ')}")

    async def write(self, obj: tuple[int, int], payload: bytes) -> None:
        _LOGGER.debug("write %s/%s = %s", obj[0], obj[1], payload.hex())
        await self._client.write_gatt_char(
            BUF_UUID, encode_write_frame(obj, payload), response=True
        )
        await self._read_until(obj)
        await self._client.write_gatt_char(CMD_UUID, bytes([1, *obj]), response=True)
        await self._read_until((0, 0))

    async def read_state(self, with_firmware: bool = False) -> TimerprogState:
        mode = (await self.read(OBJ_MODE))[0]
        eco = (await self.read(OBJ_ECO))[0]
        comfort = (await self.read(OBJ_COMFORT))[0]
        offset = int.from_bytes((await self.read(OBJ_OFFSET))[:1], "little", signed=True)
        window = (await self.read(OBJ_OPEN_WINDOW_STATUS))[0]
        firmware = None
        if with_firmware:
            minor = (await self.read(OBJ_FW_MINOR))[0]
            major = (await self.read(OBJ_FW_MAJOR))[0]
            firmware = f"{major}.{minor}"
        return TimerprogState(mode, eco, comfort, offset, window, firmware)

    async def write_thermostat(
        self, mode: int, eco_raw: int, comfort_raw: int, offset_raw: int
    ) -> None:
        """Same object order as the app's writeThermostat()."""
        if mode not in WRITABLE_MODES:
            raise TimerprogError(f"refusing to write mode {mode}")
        await self.write(OBJ_MODE, bytes([mode]))
        await self.write(OBJ_ECO, bytes([eco_raw & 0xFF]))
        await self.write(OBJ_COMFORT, bytes([comfort_raw & 0xFF]))
        await self.write(OBJ_OFFSET, bytes([offset_raw & 0xFF]))


class TimerprogClient:
    """Serialises sessions to one radiator."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._lock = asyncio.Lock()

    async def run(self, device: BLEDevice, func):
        """Run `await func(session)` in a session, trying a second session once on failure.

        Reads and writes are idempotent (a write session re-sends the full setting), so
        replaying a failed session is safe. A busy lock is not retried: the previous
        session is wedged and the next poll will try again.
        """
        try:
            return await self._run_once(device, func)
        except TimerprogBusyError:
            raise
        except TimerprogError as err:
            _LOGGER.debug("%s: session failed (%s), retrying once", device.address, err)
        await asyncio.sleep(RETRY_DELAY)
        return await self._run_once(device, func)

    async def _run_once(self, device: BLEDevice, func):
        """Open a session, run `await func(session)`, always disconnect.

        Every D-Bus/GATT call can hang when BlueZ loses track of the link, so the whole
        session is bounded, the disconnect has its own timeout, and acquiring the session
        lock is bounded too: if a previous session is wedged in an uninterruptible D-Bus
        call we give up this attempt rather than freezing every future poll. Any stale
        connection the host still holds for this address is dropped before connecting, so
        a phantom "connected" link cannot keep the radiator from advertising.
        """
        try:
            await asyncio.wait_for(self._lock.acquire(), LOCK_TIMEOUT)
        except TimeoutError as err:
            raise TimerprogBusyError(
                f"previous session still busy after {LOCK_TIMEOUT}s"
            ) from err
        client: BleakClient | None = None
        try:
            async with asyncio.timeout(SESSION_TIMEOUT):
                await close_stale_connections_by_address(device.address)
                _LOGGER.debug("%s: connecting", device.address)
                client = await establish_connection(
                    BleakClientWithServiceCache, device, self._name, max_attempts=3
                )
                session = TimerprogSession(client)
                await session.start()
                result = await func(session)
                await session.stop()
                return result
        except TimerprogError:
            raise
        except TimeoutError as err:
            raise TimerprogError(f"session timed out after {SESSION_TIMEOUT}s") from err
        except Exception as err:  # noqa: BLE001
            raise TimerprogError(f"{type(err).__name__}: {err}") from err
        finally:
            if client is not None:
                try:
                    async with asyncio.timeout(DISCONNECT_TIMEOUT):
                        await client.disconnect()
                except Exception as err:  # noqa: BLE001
                    _LOGGER.debug("%s: disconnect failed: %r", device.address, err)
                _LOGGER.debug("%s: session closed", device.address)
            self._lock.release()
