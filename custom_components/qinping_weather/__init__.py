"""Qinping Local Weather integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_AQI_SENSOR,
    CONF_CITY_ID,
    CONF_FORWARD_FIRMWARE_CHECK,
    CONF_HUMIDITY_SENSOR,
    CONF_PM10_SENSOR,
    CONF_PM25_SENSOR,
    CONF_PROXY_MODE,
    CONF_STATION_NAME,
    CONF_TIMEZONE,
    CONF_UV_SENSOR,
    CONF_WEATHER_ENTITY,
    DEFAULT_CITY_ID,
    DEFAULT_STATION_NAME,
    DOMAIN,
)
from .views import ALL_VIEW_CLASSES

_LOGGER = logging.getLogger(__name__)


def _build_state(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    data = entry.data
    weather_entity = data[CONF_WEATHER_ENTITY]
    return {
        "weather_entity_id": weather_entity,
        "build_kwargs": {
            "weather_entity_id": weather_entity,
            "station_name": data.get(CONF_STATION_NAME, DEFAULT_STATION_NAME),
            "city_id": data.get(CONF_CITY_ID, DEFAULT_CITY_ID),
            "timezone": data.get(CONF_TIMEZONE, hass.config.time_zone or "UTC"),
            "uv_sensor": data.get(CONF_UV_SENSOR) or None,
            "aqi_sensor": data.get(CONF_AQI_SENSOR) or None,
            "humidity_sensor": data.get(CONF_HUMIDITY_SENSOR) or None,
            "pm25_sensor": data.get(CONF_PM25_SENSOR) or None,
            "pm10_sensor": data.get(CONF_PM10_SENSOR) or None,
        },
        "proxy_mode": bool(data.get(CONF_PROXY_MODE, False)),
        "forward_firmware_check": bool(data.get(CONF_FORWARD_FIRMWARE_CHECK, False)),
    }


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register Qinping HTTP views on Home Assistant's HTTP server."""
    domain_state = hass.data.setdefault(DOMAIN, {})
    domain_state.update(_build_state(hass, entry))

    if not domain_state.get("views_registered"):
        for view_cls in ALL_VIEW_CLASSES:
            hass.http.register_view(view_cls(hass))
        domain_state["views_registered"] = True
        _LOGGER.info(
            "Qinping endpoints registered (proxy=%s, fw=%s, source=%s)",
            domain_state["proxy_mode"],
            domain_state["forward_firmware_check"],
            domain_state["weather_entity_id"],
        )
    else:
        _LOGGER.debug(
            "Qinping options updated (proxy=%s, fw=%s, source=%s)",
            domain_state["proxy_mode"],
            domain_state["forward_firmware_check"],
            domain_state["weather_entity_id"],
        )

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # HA HTTP has no public unregister API; routes survive until restart.
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
