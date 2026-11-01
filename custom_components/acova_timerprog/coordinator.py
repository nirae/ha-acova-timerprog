"""Polling coordinator for one Acova Timerprog radiator."""
from __future__ import annotations

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
    DEFAULT_COMFORT,
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
        # Last comfort setpoint known to be right (read in comfort mode or set by HA).
        self.comfort_raw: int = temp_to_raw(DEFAULT_COMFORT)
        # Last mode commanded from HA (used when priority = ha).
        self.desired_mode: int | None = None
        self._store: Store[dict] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")

    async def async_load(self) -> None:
        stored = await self._store.async_load() or {}
        self.comfort_raw = stored.get("comfort_raw", self.comfort_raw)
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
                state = await self._write(device, self.desired_mode, state)
            except TimerprogError as err:
                _LOGGER.warning("%s: re-apply failed: %s", self.address, err)
        return state

    def _needs_reapply(self, state: TimerprogState) -> bool:
        if self.desired_mode is None or state.mode == MODE_BOOST:
            return False  # 2h boost from the facade is always respected
        if state.mode != self.desired_mode:
            return True
        return state.mode == MODE_DAY_COMFORT and state.comfort_raw != self.comfort_raw

    async def _write(
        self, device, mode: int, current: TimerprogState | None
    ) -> TimerprogState:
        comfort = self.comfort_raw
        eco = comfort - 7  # eco = comfort - 3.5 °C, like the app
        offset = current.offset_raw if current else 0

        async def _do(session):
            await session.write_thermostat(mode, eco, comfort, offset)
            return await session.read_state()

        new = await self.client.run(device, _do)
        if self.firmware and not new.firmware:
            new = replace(new, firmware=self.firmware)
        return new

    async def async_command(self, mode: int, comfort: float | None = None) -> None:
        """Apply a mode (2, 3 or 4) and optionally a new comfort setpoint."""
        if mode not in WRITABLE_MODES:
            raise ValueError(f"mode {mode} cannot be written")
        if comfort is not None:
            self.comfort_raw = temp_to_raw(comfort)
        self.desired_mode = mode
        self._save()
        try:
            state = await self._write(self._ble_device(), mode, self.data)
        except (TimerprogError, UpdateFailed) as err:
            raise HomeAssistantError(str(err)) from err
        self.async_set_updated_data(state)

    async def async_store_comfort(self, comfort: float) -> None:
        """Remember a comfort setpoint without writing (radiator in frost mode)."""
        self.comfort_raw = temp_to_raw(comfort)
        self._save()
        self.async_update_listeners()

    @property
    def eco_mode_target(self) -> float:
        return (self.comfort_raw - 7) / 2

    @property
    def comfort_target(self) -> float:
        return self.comfort_raw / 2

