"""Config flow for Qinping Local Weather."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

from .const import (
    CONF_BIND_HOST,
    CONF_CITY_ID,
    CONF_STATION_NAME,
    CONF_TIMEZONE,
    CONF_WEATHER_ENTITY,
    DEFAULT_BIND_HOST,
    DEFAULT_CITY_ID,
    DEFAULT_PORT,
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
            vol.Required(
                CONF_PORT,
                default=defaults.get(CONF_PORT, DEFAULT_PORT),
            ): NumberSelector(
                NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_BIND_HOST,
                default=defaults.get(CONF_BIND_HOST, DEFAULT_BIND_HOST),
            ): TextSelector(),
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
        errors: dict[str, str] = {}

        if user_input is not None:
            user_input[CONF_PORT] = int(user_input[CONF_PORT])
            if not user_input.get(CONF_TIMEZONE):
                user_input[CONF_TIMEZONE] = self.hass.config.time_zone or "UTC"
            await self.async_set_unique_id(
                f"{user_input[CONF_BIND_HOST]}:{user_input[CONF_PORT]}"
            )
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"Qinping ({user_input[CONF_STATION_NAME]})",
                data=user_input,
            )

        return self.async_show_form(
            step_id="user",
            data_schema=_build_schema({}),
            errors=errors,
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
            user_input[CONF_PORT] = int(user_input[CONF_PORT])
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
