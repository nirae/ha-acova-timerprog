"""Config and options flow."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_discovered_service_info,
)
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_PRIORITY,
    CONF_SCAN_INTERVAL,
    DEFAULT_PRIORITY,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    PRIORITY_FACADE,
    PRIORITY_HA,
)
from .protocol import TimerprogClient, TimerprogError

_LOGGER = logging.getLogger(__name__)
DEFAULT_TITLE = "Acova Timerprog"


def _is_timerprog(info: BluetoothServiceInfoBleak) -> bool:
    return (info.name or "").startswith("TEMPO 3")


class AcovaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._discovered: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._address = discovery_info.address
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_confirm()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(self._address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return await self.async_step_confirm()

        current = self._async_current_ids(include_ignore=False)
        for info in async_discovered_service_info(self.hass, connectable=True):
            if _is_timerprog(info) and info.address not in current:
                self._discovered[info.address] = f"{info.name} ({info.address})"
        if not self._discovered:
            return self.async_abort(reason="no_devices_found")
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(self._discovered)}),
        )

    async def async_step_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            title = user_input.get("name") or DEFAULT_TITLE
            device = async_ble_device_from_address(self.hass, self._address, connectable=True)
            if device is None:
                errors["base"] = "cannot_connect"
            else:
                try:
                    await TimerprogClient(title).run(device, lambda s: s.read_state())
                except TimerprogError as err:
                    _LOGGER.warning("Test read failed: %s", err)
                    errors["base"] = "not_paired"
            if not errors:
                return self.async_create_entry(title=title, data={CONF_ADDRESS: self._address})
        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({vol.Optional("name", default=DEFAULT_TITLE): str}),
            description_placeholders={"address": self._address},
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return AcovaOptionsFlow()


class AcovaOptionsFlow(OptionsFlow):
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_PRIORITY, default=opts.get(CONF_PRIORITY, DEFAULT_PRIORITY)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[PRIORITY_FACADE, PRIORITY_HA],
                        translation_key="priority",
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(MIN_SCAN_INTERVAL, MAX_SCAN_INTERVAL)),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
