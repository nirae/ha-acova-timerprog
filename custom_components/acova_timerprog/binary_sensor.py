"""Binary sensors: 2h boost running, open-window detection enabled."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AcovaConfigEntry
from .entity import AcovaEntity
from .protocol import MODE_BOOST


async def async_setup_entry(
    hass: HomeAssistant, entry: AcovaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities([AcovaBoost(coordinator), AcovaOpenWindowDetection(coordinator)])


class AcovaBoost(AcovaEntity, BinarySensorEntity):
    _attr_translation_key = "boost"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "boost")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.mode == MODE_BOOST


class AcovaOpenWindowDetection(AcovaEntity, BinarySensorEntity):
    _attr_translation_key = "open_window_detection"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "open_window_detection")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.open_window_status & 1)
