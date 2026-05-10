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
    OPTIONAL_SENSOR_KEYS,
)


def _sensor_selector() -> EntitySelector:
    return EntitySelector(EntitySelectorConfig(domain="sensor"))


def _build_schema(defaults: dict[str, Any]) -> vol.Schema:
    schema: dict[Any, Any] = {
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
    for key in OPTIONAL_SENSOR_KEYS:
        existing = defaults.get(key)
        if existing:
            schema[vol.Optional(key, default=existing)] = _sensor_selector()
        else:
            schema[vol.Optional(key)] = _sensor_selector()
    return vol.Schema(schema)


def _normalise(user_input: dict[str, Any], hass) -> dict[str, Any]:
    if not user_input.get(CONF_TIMEZONE):
        user_input[CONF_TIMEZONE] = hass.config.time_zone or "UTC"
    for key in OPTIONAL_SENSOR_KEYS:
        if user_input.get(key) in ("", None):
            user_input.pop(key, None)
    return user_input


class QinpingConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> Any:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            user_input = _normalise(user_input, self.hass)
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
            user_input = _normalise(user_input, self.hass)
            self.hass.config_entries.async_update_entry(
                self._entry, data={**self._entry.data, **user_input}
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=_build_schema(dict(self._entry.data)),
        )
