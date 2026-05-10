"""Config flow for Qinping Local Weather."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    TextSelector,
)

from .const import (
    CONF_CITY_ID,
    CONF_STATION_NAME,
    CONF_TIMEZONE,
    CONF_WEATHER_ENTITY,
    DEFAULT_CITY_ID,
    DEFAULT_STATION_NAME,
    DOMAIN,
)


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(
                CONF_WEATHER_ENTITY,
                default=defaults.get(CONF_WEATHER_ENTITY),
            ): EntitySelector(EntitySelectorConfig(domain="weather")),
            vol.Optional(
                CONF_STATION_NAME,
                default=defaults.get(CONF_STATION_NAME, DEFAULT_STATION_NAME),
            ): TextSelector(),
            vol.Optional(
                CONF_CITY_ID,
                default=defaults.get(CONF_CITY_ID, DEFAULT_CITY_ID),
            ): TextSelector(),
            vol.Optional(
                CONF_TIMEZONE,
                default=defaults.get(CONF_TIMEZONE, ""),
            ): TextSelector(),
        }
    )


class QinpingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            if not user_input.get(CONF_TIMEZONE):
                user_input[CONF_TIMEZONE] = self.hass.config.time_zone or "UTC"
            return self.async_create_entry(
                title=f"Qinping ({user_input[CONF_STATION_NAME]})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema({}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return QinpingOptionsFlow(config_entry)


class QinpingOptionsFlow(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if user_input is not None:
            if not user_input.get(CONF_TIMEZONE):
                user_input[CONF_TIMEZONE] = self.hass.config.time_zone or "UTC"
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, **user_input}
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(dict(self._entry.data)),
        )
