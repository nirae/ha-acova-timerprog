"""Button to refresh the radiator state on demand."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AcovaConfigEntry
from .entity import AcovaEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: AcovaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AcovaRefresh(entry.runtime_data)])


class AcovaRefresh(AcovaEntity, ButtonEntity):
    """Force an immediate Bluetooth poll (also usable while unavailable to kick a retry)."""

    _attr_translation_key = "refresh"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "refresh")

    @property
    def available(self) -> bool:
        # Stays pressable even when the last poll failed: that is exactly when the
        # user wants to retry reading the radiator.
        return True

    async def async_press(self) -> None:
        await self.coordinator.async_request_refresh()
