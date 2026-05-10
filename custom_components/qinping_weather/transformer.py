"""Build Qinping cloud-format JSON payloads from a Home Assistant weather entity.

Output shape mirrors ea/cgs2_decloud weather_server.py so the device accepts it
unchanged.
"""
from __future__ import annotations

import time
from typing import Any

from homeassistant.components.weather import (
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_PRESSURE,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_WIND_BEARING,
    ATTR_WEATHER_WIND_SPEED,
    ATTR_WEATHER_WIND_SPEED_UNIT,
)
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant, State
from homeassistant.util.unit_conversion import SpeedConverter

# Caiyun-style condition codes the QingSnow2App expects.
_HA_TO_SKYCON: dict[str, str] = {
    "clear-night": "CLEAR_NIGHT",
    "sunny": "CLEAR_DAY",
    "partlycloudy": "PARTLY_CLOUDY_DAY",
    "cloudy": "CLOUDY",
    "fog": "FOG",
    "hail": "HAIL",
    "lightning": "STORM_RAIN",
    "lightning-rainy": "STORM_RAIN",
    "pouring": "HEAVY_RAIN",
    "rainy": "MODERATE_RAIN",
    "snowy": "MODERATE_SNOW",
    "snowy-rainy": "SLEET",
    "windy": "WIND",
    "windy-variant": "WIND",
    "exceptional": "CLEAR_DAY",
}

_CARDINALS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _bearing_to_cardinal(bearing: float | None) -> str:
    if bearing is None:
        return "N/A"
    return _CARDINALS[int((bearing % 360) / 22.5)]


def _wind_speed_kmh(state: State) -> float:
    speed = state.attributes.get(ATTR_WEATHER_WIND_SPEED)
    if speed is None:
        return 0.0
    unit = state.attributes.get(ATTR_WEATHER_WIND_SPEED_UNIT, UnitOfSpeed.KILOMETERS_PER_HOUR)
    try:
        return float(SpeedConverter.convert(float(speed), unit, UnitOfSpeed.KILOMETERS_PER_HOUR))
    except (ValueError, TypeError):
        return 0.0


def build_payloads(
    hass: HomeAssistant,
    weather_entity_id: str,
    *,
    station_name: str,
    city_id: str,
    timezone: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (weather_payload, location_payload) wrapped to match cgs2_decloud."""

    state = hass.states.get(weather_entity_id)

    if state is None:
        # Source entity missing — return zeroed but well-formed structures so
        # the device doesn't crash on its side.
        temperature = 0.0
        humidity = 0
        wind_speed = 0.0
        wind_bearing: float | None = None
        skycon = "CLEAR_DAY"
    else:
        temp_attr = state.attributes.get(ATTR_WEATHER_TEMPERATURE)
        temperature = float(temp_attr) if temp_attr is not None else 0.0

        humidity_attr = state.attributes.get(ATTR_WEATHER_HUMIDITY)
        humidity = int(round(float(humidity_attr))) if humidity_attr is not None else 0

        wind_speed = _wind_speed_kmh(state)
        wind_bearing = state.attributes.get(ATTR_WEATHER_WIND_BEARING)

        skycon = _HA_TO_SKYCON.get(state.state, "CLEAR_DAY")

    latitude = str(hass.config.latitude)
    longitude = str(hass.config.longitude)
    pub_time = int(time.time())

    location = {
        "city_id": city_id,
        "name": station_name,
        "name_cn": "",
        "name_en": station_name,
        "country": "",
    }

    weather = {
        "city": {
            "city": station_name,
            "cityId": city_id,
            "cnAddress": {
                "city": "",
                "cityId": city_id,
                "country": "",
                "province": "",
            },
            "cnCity": "",
            "country": "",
            "enAddress": {
                "city": station_name,
                "cityId": city_id,
                "country": "",
                "province": "",
            },
            "latitude": latitude,
            "longitude": longitude,
            "name": station_name,
            "name_cn": "",
            "name_cn_tw": "",
            "name_en": station_name,
            "province": "",
            "timezone": timezone,
            "timezoneFmt": "UTC",
        },
        "city_id": city_id,
        "weather": {
            "aqi": 0,
            "aqi_day_max_cn": 0,
            "aqi_day_max_en": 0,
            "aqi_day_min_cn": 0,
            "aqi_day_min_en": 0,
            "aqi_us": 0,
            "co": 0.0,
            "co_us": 0.0,
            "no2": 0,
            "no2_us": 0,
            "noAqi": True,
            "o3": 0,
            "o3_us": 0.0,
            "pm10": 0,
            "pm25": 0,
            "so2": 0,
            "so2_us": 0,
            "humidity": humidity,
            "probability": 0,
            "pub_time": pub_time,
            "skycon": skycon,
            "temp_max": temperature,
            "temp_min": temperature,
            "temperature": temperature,
            "ultraviolet": 0,
            "vehicle_limit": {"type": "city_unlimited"},
            "wind": {
                "speed": round(wind_speed, 2),
                "wind_dir": _bearing_to_cardinal(wind_bearing),
                "wind_level": int(wind_speed / 5),
            },
        },
    }

    return weather, location
