"""Climate entity: heat/off (off = frost protection), presets comfort/eco."""
from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    PRESET_BOOST,
    PRESET_COMFORT,
    PRESET_ECO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import AcovaConfigEntry
from .const import DOMAIN, ECO_DELTA, FROST_TEMP, MAX_TEMP, MIN_TEMP
from .entity import AcovaEntity
from .protocol import (
    MODE_AUTO,
    MODE_BOOST,
    MODE_DAY_COMFORT,
    MODE_FROST,
    MODE_NIGHT_ECO,
    MODE_STANDBY,
    MODE_USER_PROGRAM,
)

PRESET_AUTO = "auto"  # set from the facade (e.g. after power-on)
PRESET_PROGRAM = "program"  # app's custom weekly program

MODE_TO_PRESET = {
    MODE_DAY_COMFORT: PRESET_COMFORT,
    MODE_NIGHT_ECO: PRESET_ECO,
    MODE_BOOST: PRESET_BOOST,
    MODE_AUTO: PRESET_AUTO,
    MODE_USER_PROGRAM: PRESET_PROGRAM,
}
SETTABLE_PRESETS = {PRESET_COMFORT: MODE_DAY_COMFORT, PRESET_ECO: MODE_NIGHT_ECO}


async def async_setup_entry(
    hass: HomeAssistant, entry: AcovaConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([AcovaClimate(entry.runtime_data)])


class AcovaClimate(AcovaEntity, ClimateEntity):
    _attr_name = None
    _attr_translation_key = "radiator"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 0.5
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "climate")

    @property
    def _mode(self) -> int:
        return self.coordinator.data.mode

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.OFF if self._mode in (MODE_FROST, MODE_STANDBY) else HVACMode.HEAT

    @property
    def preset_mode(self) -> str | None:
        return MODE_TO_PRESET.get(self._mode)

    @property
    def preset_modes(self) -> list[str]:
        presets = [PRESET_COMFORT, PRESET_ECO]
        current = self.preset_mode
        if current and current not in presets:
            presets.append(current)
        return presets

    @property
    def target_temperature(self) -> float | None:
        data = self.coordinator.data
        if self._mode == MODE_DAY_COMFORT:
            return data.comfort
        if self._mode == MODE_NIGHT_ECO:
            return self.coordinator.eco_mode_target
        if self._mode in (MODE_FROST, MODE_STANDBY):
            return None  # frost is not adjustable: no setpoint shown when off
        return data.comfort  # auto / boost / program: what the radiator reports

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "raw_mode": data.mode,
            "comfort_setpoint": self.coordinator.comfort_target,
            "eco_setpoint": self.coordinator.eco_mode_target,
            "radiator_comfort_register": data.comfort,
            "radiator_eco_register": data.eco,
            "priority": self.coordinator.priority,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.async_command(MODE_FROST)
        else:
            await self.async_turn_on()

    async def async_turn_on(self) -> None:
        desired = self.coordinator.desired_mode
        mode = desired if desired in (MODE_DAY_COMFORT, MODE_NIGHT_ECO) else MODE_DAY_COMFORT
        await self.coordinator.async_command(mode)

    async def async_turn_off(self) -> None:
        await self.coordinator.async_command(MODE_FROST)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode not in SETTABLE_PRESETS:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="preset_not_settable",
                translation_placeholders={"preset": preset_mode},
            )
        await self.coordinator.async_command(SETTABLE_PRESETS[preset_mode])

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get(ATTR_TEMPERATURE)
        if temp is None:
            return
        if self._mode == MODE_NIGHT_ECO:
            # the slider shows the eco target; store the matching comfort setpoint
            await self.coordinator.async_command(MODE_NIGHT_ECO, comfort=temp + ECO_DELTA)
        elif self._mode == MODE_DAY_COMFORT:
            await self.coordinator.async_command(MODE_DAY_COMFORT, comfort=temp)
        elif self._mode in (MODE_FROST, MODE_STANDBY):
            # frost is not adjustable from HA: ignore (the radiator forces 7 °C)
            return
        else:
            # auto / boost / program from the facade: an explicit HA change means comfort
            await self.coordinator.async_command(MODE_DAY_COMFORT, comfort=temp)
