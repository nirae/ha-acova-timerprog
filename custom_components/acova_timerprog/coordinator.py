"""Polling coordinator for one Acova Timerprog radiator."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import timedelta
import logging

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_PRIORITY,
    CONF_SCAN_INTERVAL,
    DEFAULT_PRIORITY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PRIORITY_HA,
)
from .protocol import (
    MODE_BOOST,
    MODE_DAY_COMFORT,
    WRITABLE_MODES,
    TimerprogClient,
    TimerprogError,
    TimerprogState,
    temp_to_raw,
)

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
MODE_SETTLE_TRIES = 6
MODE_SETTLE_DELAY = 0.5


class AcovaCoordinator(DataUpdateCoordinator[TimerprogState]):
    """Reads the radiator every scan_interval and applies commands."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {entry.data[CONF_ADDRESS]}",
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )
        self.address: str = entry.data[CONF_ADDRESS]
        self.priority: str = entry.options.get(CONF_PRIORITY, DEFAULT_PRIORITY)
        self.client = TimerprogClient(entry.title)
        self.firmware: str | None = None
        # Comfort setpoint known to be right (read in comfort mode or set by HA), None
        # until then. Only shown and used to compute the eco target: mode changes never
        # write it, the radiator keeps its own setpoints.
        self.comfort_raw: int | None = None
        # Last mode commanded from HA (used when priority = ha).
        self.desired_mode: int | None = None
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.comfort_raw = stored.get("comfort_raw")
        self.desired_mode = stored.get("desired_mode")

    def _save(self) -> None:
        self._store.async_delay_save(
            lambda: {"comfort_raw": self.comfort_raw, "desired_mode": self.desired_mode}, 1
        )

    def _ble_device(self):
        device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if device is None:
            raise UpdateFailed(
                f"{self.address} not seen by Bluetooth (radiator off with the power button?)"
            )
        return device

    async def _async_update_data(self) -> TimerprogState:
        device = self._ble_device()
        first = self.firmware is None
        try:
            state = await self.client.run(device, lambda s: s.read_state(with_firmware=first))
        except TimerprogError as err:
            raise UpdateFailed(str(err)) from err
        if state.firmware:
            self.firmware = state.firmware
        if state.mode == MODE_DAY_COMFORT and state.comfort_raw != self.comfort_raw:
            self.comfort_raw = state.comfort_raw
            self._save()

        if self.priority == PRIORITY_HA and self._needs_reapply(state):
            _LOGGER.info(
                "%s: radiator mode %s differs from HA mode %s, re-applying",
                self.address, state.mode, self.desired_mode,
            )
            try:
                state = await self._write(device, self.desired_mode)
            except TimerprogError as err:
                _LOGGER.warning("%s: re-apply failed: %s", self.address, err)
        return state

    def _needs_reapply(self, state: TimerprogState) -> bool:
        if self.desired_mode is None or state.mode == MODE_BOOST:
            return False  # 2h boost from the facade is always respected
        return state.mode != self.desired_mode

    @staticmethod
    async def _settle(session, mode: int) -> TimerprogState:
        """Read the state, giving the radiator a moment to report the new mode."""
        state = await session.read_state()
        for _ in range(MODE_SETTLE_TRIES):
            if state.mode == mode:
                break
            await asyncio.sleep(MODE_SETTLE_DELAY)
            state = await session.read_state()
        return state

    async def _write(
        self, device, mode: int, comfort_raw: int | None = None,
        current: TimerprogState | None = None,
    ) -> TimerprogState:
        """Write the mode alone, or the full setting when a new comfort is given."""

        async def _do(session):
            if comfort_raw is None:
                await session.write_mode(mode)
            else:
                eco = comfort_raw - 7  # eco = comfort - 3.5 °C, like the app
                offset = current.offset_raw if current else 0
                await session.write_thermostat(mode, eco, comfort_raw, offset)
            state = await self._settle(session, mode)
            if state.mode != mode:
                # A mode change sent seconds after another one can be ignored: send it again.
                _LOGGER.debug("%s: mode %s not applied, sending it again", self.address, mode)
                await session.write_mode(mode)
                state = await self._settle(session, mode)
            return state

        new = await self.client.run(device, _do)
        if self.firmware and not new.firmware:
            new = replace(new, firmware=self.firmware)
        return new

    async def async_command(self, mode: int, comfort: float | None = None) -> None:
        """Apply a mode (2, 3 or 4) and optionally a new comfort setpoint."""
        if mode not in WRITABLE_MODES:
            raise ValueError(f"mode {mode} cannot be written")
        comfort_raw = temp_to_raw(comfort) if comfort is not None else None
        try:
            state = await self._write(self._ble_device(), mode, comfort_raw, self.data)
        except (TimerprogError, UpdateFailed) as err:
            raise HomeAssistantError(str(err)) from err
        if comfort_raw is not None:
            self.comfort_raw = comfort_raw
        if state.mode == MODE_DAY_COMFORT:
            self.comfort_raw = state.comfort_raw
        self.desired_mode = mode
        self._save()
        self.async_set_updated_data(state)

    @property
    def eco_mode_target(self) -> float | None:
        return None if self.comfort_raw is None else (self.comfort_raw - 7) / 2

    @property
    def comfort_target(self) -> float | None:
        return None if self.comfort_raw is None else self.comfort_raw / 2

