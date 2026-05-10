"""Qinping Local Weather integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CITY_ID,
    CONF_STATION_NAME,
    CONF_TIMEZONE,
    CONF_WEATHER_ENTITY,
    DEFAULT_CITY_ID,
    DEFAULT_STATION_NAME,
    DOMAIN,
)
from .views import ALL_VIEW_CLASSES

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Register Qinping HTTP views on Home Assistant's HTTP server."""
    data = entry.data
    kwargs = dict(
        weather_entity=data[CONF_WEATHER_ENTITY],
        station_name=data.get(CONF_STATION_NAME, DEFAULT_STATION_NAME),
        city_id=data.get(CONF_CITY_ID, DEFAULT_CITY_ID),
        timezone=data.get(CONF_TIMEZONE, hass.config.time_zone or "UTC"),
    )

    for view_cls in ALL_VIEW_CLASSES:
        hass.http.register_view(view_cls(hass, **kwargs))

    _LOGGER.info(
        "Qinping endpoints registered on HA HTTP (source: %s)", kwargs["weather_entity"]
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = kwargs

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Home Assistant's HTTP component does not expose a public unregister API,
    # so the routes stay bound until restart. We just drop our state.
    hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
