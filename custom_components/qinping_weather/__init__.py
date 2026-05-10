"""Qinping Local Weather integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    CONF_BIND_HOST,
    CONF_CITY_ID,
    CONF_PORT,
    CONF_STATION_NAME,
    CONF_TIMEZONE,
    CONF_WEATHER_ENTITY,
    DEFAULT_BIND_HOST,
    DEFAULT_CITY_ID,
    DEFAULT_PORT,
    DEFAULT_STATION_NAME,
    DOMAIN,
)
from .server import QinpingServer

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Bring up the Qinping weather server for a config entry."""
    ssl_certificate = getattr(hass.http, "ssl_certificate", None)
    ssl_key = getattr(hass.http, "ssl_key", None)

    if not ssl_certificate or not ssl_key:
        raise ConfigEntryNotReady(
            "Home Assistant has no ssl_certificate / ssl_key configured under "
            "the http: integration. Configure HTTPS for HA first — Qinping "
            "devices require TLS."
        )

    data = entry.data
    server = QinpingServer(
        hass,
        bind_host=data.get(CONF_BIND_HOST, DEFAULT_BIND_HOST),
        port=data.get(CONF_PORT, DEFAULT_PORT),
        weather_entity=data[CONF_WEATHER_ENTITY],
        station_name=data.get(CONF_STATION_NAME, DEFAULT_STATION_NAME),
        city_id=data.get(CONF_CITY_ID, DEFAULT_CITY_ID),
        timezone=data.get(CONF_TIMEZONE, hass.config.time_zone or "UTC"),
        ssl_certificate=ssl_certificate,
        ssl_key=ssl_key,
    )

    try:
        await server.start()
    except OSError as err:
        raise ConfigEntryNotReady(f"Failed to bind Qinping server: {err}") from err

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = server

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    server: QinpingServer | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if server is not None:
        await server.stop()
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
