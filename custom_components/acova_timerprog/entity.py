"""Base entity."""
from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AcovaCoordinator


class AcovaEntity(CoordinatorEntity[AcovaCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: AcovaCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{coordinator.address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.address)},
            connections={(CONNECTION_BLUETOOTH, coordinator.address)},
            name=entry.title,
            manufacturer="Acova",
            model="Timerprog Bluetooth (TEMPO 3)",
            sw_version=coordinator.firmware,
        )
