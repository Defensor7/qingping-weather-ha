"""Build Qinping cloud-format JSON payloads from HA state.

Output shape mirrors ea/cgs2_decloud weather_server.py so the device accepts it
unchanged.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any

from homeassistant.components.weather import (
    ATTR_WEATHER_HUMIDITY,
    ATTR_WEATHER_TEMPERATURE,
    ATTR_WEATHER_WIND_BEARING,
    ATTR_WEATHER_WIND_SPEED,
    ATTR_WEATHER_WIND_SPEED_UNIT,
)
from homeassistant.const import UnitOfSpeed
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import SpeedConverter

_LOGGER = logging.getLogger(__name__)

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


def _read_sensor_float(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in (None, "", "unknown", "unavailable"):
        return None
    try:
        return float(state.state)
    except (ValueError, TypeError):
        return None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (ValueError, TypeError):
        return default


async def _fetch_forecast(
    hass: HomeAssistant, weather_entity_id: str, forecast_type: str
) -> list[dict[str, Any]]:
    """Call the weather.get_forecasts service and unwrap its response.

    Returns [] (with a debug log line) if the entity does not advertise the
    requested forecast type — this is normal for integrations like
    HA-YandexWeather that only expose `hourly`.
    """
    try:
        response = await hass.services.async_call(
            "weather",
            "get_forecasts",
            {"entity_id": weather_entity_id, "type": forecast_type},
            blocking=True,
            return_response=True,
        )
    except Exception as err:
        _LOGGER.warning(
            "weather.get_forecasts(%s, type=%s) failed: %s",
            weather_entity_id,
            forecast_type,
            err,
        )
        return []
    if not response:
        return []
    entity_response = response.get(weather_entity_id) or {}
    forecast = list(entity_response.get("forecast") or [])
    if not forecast:
        _LOGGER.debug(
            "weather.get_forecasts(%s, type=%s) returned no entries",
            weather_entity_id,
            forecast_type,
        )
    return forecast


def _bucket_key_local_date(datetime_str: str | None) -> str | None:
    if not datetime_str:
        return None
    parsed = dt_util.parse_datetime(datetime_str)
    if parsed is None:
        return None
    return dt_util.as_local(parsed).date().isoformat()


def _aggregate_hourly_to_daily(
    hourly: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Roll up hourly forecast entries into per-day buckets.

    Used as a fallback when the source entity exposes only `hourly` (e.g.
    HA-YandexWeather). Yandex returns ~48h, which yields 2 daily entries.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    for entry in hourly:
        key = _bucket_key_local_date(entry.get("datetime"))
        if key is None:
            continue
        buckets.setdefault(key, []).append(entry)

    out: list[dict[str, Any]] = []
    for date_key in sorted(buckets):
        items = buckets[date_key]
        temps = [
            float(e["temperature"]) for e in items if e.get("temperature") is not None
        ]
        humidities = [
            float(e["humidity"]) for e in items if e.get("humidity") is not None
        ]
        wind_speeds = [
            float(e["wind_speed"]) for e in items if e.get("wind_speed") is not None
        ]
        wind_bearings = [
            e["wind_bearing"] for e in items if e.get("wind_bearing") is not None
        ]
        probabilities = [
            float(e["precipitation_probability"])
            for e in items
            if e.get("precipitation_probability") is not None
        ]
        conditions = [e.get("condition") for e in items if e.get("condition")]

        out.append(
            {
                "datetime": f"{date_key}T12:00:00",
                "condition": Counter(conditions).most_common(1)[0][0]
                if conditions
                else "",
                "temperature": max(temps) if temps else None,
                "templow": min(temps) if temps else None,
                "humidity": (sum(humidities) / len(humidities)) if humidities else None,
                "wind_speed": (sum(wind_speeds) / len(wind_speeds))
                if wind_speeds
                else None,
                "wind_bearing": wind_bearings[0] if wind_bearings else None,
                "precipitation_probability": max(probabilities)
                if probabilities
                else None,
            }
        )
    return out


def _forecast_entry_weather(fc: dict[str, Any], ultraviolet: int) -> dict[str, Any]:
    condition = fc.get("condition") or ""
    temp_high = _safe_float(fc.get("temperature"))
    temp_low = _safe_float(fc.get("templow"), default=temp_high)
    humidity = _safe_float(fc.get("humidity"))
    wind_speed = _safe_float(fc.get("wind_speed"))
    wind_bearing = fc.get("wind_bearing")
    probability = _safe_float(fc.get("precipitation_probability"))

    return {
        "date": fc.get("datetime", ""),
        "skycon": _HA_TO_SKYCON.get(condition, "CLEAR_DAY"),
        "temp_max": temp_high,
        "temp_min": temp_low,
        "humidity": int(round(humidity)),
        "probability": int(round(probability)),
        "ultraviolet": ultraviolet,
        "wind": {
            "speed": round(wind_speed, 2),
            "wind_dir": _bearing_to_cardinal(wind_bearing),
            "wind_level": int(wind_speed / 5),
        },
    }


async def build_weather_forecast(
    hass: HomeAssistant,
    weather_entity_id: str,
    forecast_type: str,
    *,
    uv_sensor: str | None = None,
) -> list[dict[str, Any]]:
    """Return a list of forecast entries in Qinping shape (top-level array).

    For type="daily" the source entity may not advertise FORECAST_DAILY
    (HA-YandexWeather only exposes hourly). The fallback chain is:
        daily -> twice_daily -> aggregate(hourly).
    """
    forecasts: list[dict[str, Any]] = []
    if forecast_type == "hourly":
        forecasts = await _fetch_forecast(hass, weather_entity_id, "hourly")
    else:  # "daily" or anything else — try hardest to produce daily data
        forecasts = await _fetch_forecast(hass, weather_entity_id, "daily")
        if not forecasts:
            forecasts = await _fetch_forecast(
                hass, weather_entity_id, "twice_daily"
            )
        if not forecasts:
            hourly = await _fetch_forecast(hass, weather_entity_id, "hourly")
            forecasts = _aggregate_hourly_to_daily(hourly)
            if forecasts:
                _LOGGER.debug(
                    "Synthesised %d daily entries from hourly forecast for %s",
                    len(forecasts),
                    weather_entity_id,
                )

    uv_value = _read_sensor_float(hass, uv_sensor)
    ultraviolet = int(round(uv_value)) if uv_value is not None else 0
    return [_forecast_entry_weather(fc, ultraviolet) for fc in forecasts]


def build_aqi_forecast_placeholder() -> list[dict[str, Any]]:
    """No AQI source wired up yet — return empty array.

    The device tolerates an empty top-level array (graphs just have no points).
    """
    return []


def build_payloads(
    hass: HomeAssistant,
    weather_entity_id: str,
    *,
    station_name: str,
    city_id: str,
    timezone: str,
    uv_sensor: str | None = None,
    aqi_sensor: str | None = None,
    humidity_sensor: str | None = None,
    pm25_sensor: str | None = None,
    pm10_sensor: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (weather_payload, location_payload) wrapped to match cgs2_decloud."""

    state = hass.states.get(weather_entity_id)

    if state is None:
        temperature = 0.0
        humidity_from_weather: float | None = None
        wind_speed = 0.0
        wind_bearing: float | None = None
        skycon = "CLEAR_DAY"
    else:
        temp_attr = state.attributes.get(ATTR_WEATHER_TEMPERATURE)
        temperature = float(temp_attr) if temp_attr is not None else 0.0

        humidity_attr = state.attributes.get(ATTR_WEATHER_HUMIDITY)
        humidity_from_weather = (
            float(humidity_attr) if humidity_attr is not None else None
        )

        wind_speed = _wind_speed_kmh(state)
        wind_bearing = state.attributes.get(ATTR_WEATHER_WIND_BEARING)

        skycon = _HA_TO_SKYCON.get(state.state, "CLEAR_DAY")

    humidity_override = _read_sensor_float(hass, humidity_sensor)
    humidity_value = humidity_override if humidity_override is not None else humidity_from_weather
    humidity = int(round(humidity_value)) if humidity_value is not None else 0

    uv_value = _read_sensor_float(hass, uv_sensor)
    ultraviolet = int(round(uv_value)) if uv_value is not None else 0

    aqi_value = _read_sensor_float(hass, aqi_sensor)
    aqi = int(round(aqi_value)) if aqi_value is not None else 0
    no_aqi = aqi_value is None

    pm25_value = _read_sensor_float(hass, pm25_sensor)
    pm25 = int(round(pm25_value)) if pm25_value is not None else 0

    pm10_value = _read_sensor_float(hass, pm10_sensor)
    pm10 = int(round(pm10_value)) if pm10_value is not None else 0

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
            "aqi": aqi,
            "aqi_day_max_cn": aqi,
            "aqi_day_max_en": aqi,
            "aqi_day_min_cn": aqi,
            "aqi_day_min_en": aqi,
            "aqi_us": aqi,
            "co": 0.0,
            "co_us": 0.0,
            "no2": 0,
            "no2_us": 0,
            "noAqi": no_aqi,
            "o3": 0,
            "o3_us": 0.0,
            "pm10": pm10,
            "pm25": pm25,
            "so2": 0,
            "so2_us": 0,
            "humidity": humidity,
            "probability": 0,
            "pub_time": pub_time,
            "skycon": skycon,
            "temp_max": temperature,
            "temp_min": temperature,
            "temperature": temperature,
            "ultraviolet": ultraviolet,
            "vehicle_limit": {"type": "city_unlimited"},
            "wind": {
                "speed": round(wind_speed, 2),
                "wind_dir": _bearing_to_cardinal(wind_bearing),
                "wind_level": int(wind_speed / 5),
            },
        },
    }

    return weather, location
