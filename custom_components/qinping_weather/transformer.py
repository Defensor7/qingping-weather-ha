"""Build Qinping cloud-format JSON payloads from HA state.

Schemas verified against the live qing.cleargrass.com responses (captured
via the debug/qinping_capture.py MITM proxy, May 2026):

  GET /daily/weatherNow            -> {"code":0,"data":<weather_obj>}   (cgs2_decloud-compatible)
  GET /daily/dailyForecasts?...    -> {"code":0,"data":[<daily_entry>...]}
  GET /daily/hourlyForecasts?...   -> {"code":0,"data":[<hourly_entry>...]}

Daily and hourly entries use different nested-object shapes; see
_daily_entry / _hourly_entry below.
"""
from __future__ import annotations

import logging
import time
from collections import Counter
from typing import Any, Iterable

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
    "rainy": "RAIN",
    "snowy": "SNOW",
    "snowy-rainy": "SLEET",
    "windy": "WIND",
    "windy-variant": "WIND",
    "exceptional": "CLEAR_DAY",
}

_DAY_TO_NIGHT_SKYCON: dict[str, str] = {
    "CLEAR_DAY": "CLEAR_NIGHT",
    "PARTLY_CLOUDY_DAY": "PARTLY_CLOUDY_NIGHT",
}

_CARDINALS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def _bearing_to_cardinal(bearing: float | None) -> str:
    # Real upstream always sends a valid cardinal like "ESE"; the device's
    # parser appears not to tolerate non-cardinal strings, so fall back to "N".
    if bearing is None:
        return "N"
    return _CARDINALS[int((bearing % 360) / 22.5)]


def _bearing_to_octant16(bearing: float | None) -> int | None:
    """0-15 octant, where the live server appears to use this scheme for daily."""
    if bearing is None:
        return None
    return int((bearing % 360) / 22.5)


def _wind_level_from_speed_kmh(speed: float) -> int:
    """Beaufort-ish bucketing: cap at 12, ~5 km/h per step (matches device UI)."""
    return max(0, min(12, int(speed / 5)))


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


# ---------------------------------------------------------------------------
# /daily/weatherNow — already known-good shape from cgs2_decloud
# ---------------------------------------------------------------------------


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
    """Return (weather_payload, location_payload) for /daily/weatherNow + /daily/locate."""

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
            "cnAddress": {"city": "", "cityId": city_id, "country": "", "province": ""},
            "cnCity": "",
            "country": "",
            "enAddress": {"city": station_name, "cityId": city_id, "country": "", "province": ""},
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
                "wind_level": _wind_level_from_speed_kmh(wind_speed),
            },
        },
    }

    return weather, location


# ---------------------------------------------------------------------------
# Forecast plumbing
# ---------------------------------------------------------------------------


async def _fetch_forecast(
    hass: HomeAssistant, weather_entity_id: str, forecast_type: str
) -> list[dict[str, Any]]:
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
            weather_entity_id, forecast_type, err,
        )
        return []
    if not response:
        return []
    return list((response.get(weather_entity_id) or {}).get("forecast") or [])


def _parse_dt(s: str | None):
    if not s:
        return None
    parsed = dt_util.parse_datetime(s)
    if parsed is None:
        return None
    return dt_util.as_local(parsed)


def _hourly_forecast_to_kmh(entry: dict[str, Any]) -> float:
    """HA forecast `wind_speed` unit isn't always km/h; we trust km/h for Yandex."""
    return _safe_float(entry.get("wind_speed"))


def _humidity_fraction(percent: Any) -> float:
    """Real server returns 0..1; HA returns 0..100. Convert."""
    return round(_safe_float(percent) / 100.0, 4)


def _condition_to_skycon(condition: str | None, *, is_night: bool = False) -> str:
    base = _HA_TO_SKYCON.get(condition or "", "CLEAR_DAY")
    if is_night:
        return _DAY_TO_NIGHT_SKYCON.get(base, base)
    return base


def _is_night_hour(hour: int) -> bool:
    return hour < 6 or hour >= 19


# ---------------------------------------------------------------------------
# Hourly entry (matches /daily/hourlyForecasts?metric=weather upstream shape)
# ---------------------------------------------------------------------------


def _hourly_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    dt = _parse_dt(entry.get("datetime"))
    if dt is None:
        return None
    dt_str = dt.strftime("%Y-%m-%d %H:%M")
    timestamp = int(dt.timestamp())
    is_night = _is_night_hour(dt.hour)
    skycon = _condition_to_skycon(entry.get("condition"), is_night=is_night)
    wind_speed = _hourly_forecast_to_kmh(entry)
    wind_bearing = entry.get("wind_bearing")
    return {
        "datetime": dt_str,
        "timestamp": timestamp,
        "date": dt_str,
        "skycon": {"date": dt_str, "value": skycon},
        "wind": {
            "datetime": dt_str,
            "value": {
                "wind_dir": _bearing_to_cardinal(wind_bearing),
                "wind_level": _wind_level_from_speed_kmh(wind_speed),
                "speed": round(wind_speed, 2),
            },
        },
        "temperature": {
            "datetime": dt_str,
            "timestamp": timestamp,
            "value": _safe_float(entry.get("temperature")),
        },
        "humidity": {
            "datetime": dt_str,
            "timestamp": timestamp,
            "value": _humidity_fraction(entry.get("humidity")),
        },
        "pm25": {
            "datetime": dt_str,
            "timestamp": timestamp,
            "value": 0,
        },
    }


async def build_hourly_weather_forecast(
    hass: HomeAssistant, weather_entity_id: str
) -> list[dict[str, Any]]:
    raw = await _fetch_forecast(hass, weather_entity_id, "hourly")
    out: list[dict[str, Any]] = []
    for entry in raw:
        result = _hourly_entry(entry)
        if result is not None:
            out.append(result)
    return out


# ---------------------------------------------------------------------------
# Daily entry (matches /daily/dailyForecasts?metric=weather upstream shape)
# ---------------------------------------------------------------------------


def _agg_max_min_avg(values: Iterable[float | None]) -> tuple[float, float, float]:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return 0.0, 0.0, 0.0
    return max(nums), min(nums), round(sum(nums) / len(nums), 2)


def _most_common(values: Iterable[Any]) -> Any:
    items = [v for v in values if v is not None]
    if not items:
        return None
    return Counter(items).most_common(1)[0][0]


def _daily_buckets(
    hourly_raw: list[dict[str, Any]],
) -> list[tuple[str, int, list[dict[str, Any]]]]:
    """Group hourly entries by local date. Returns list of (date_str, midnight_ts, items)
    in chronological order."""
    buckets: dict[str, list[dict[str, Any]]] = {}
    midnights: dict[str, int] = {}
    for entry in hourly_raw:
        dt = _parse_dt(entry.get("datetime"))
        if dt is None:
            continue
        date_key = dt.date().isoformat()
        buckets.setdefault(date_key, []).append(entry)
        if date_key not in midnights:
            midnight = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            midnights[date_key] = int(midnight.timestamp())
    return [(d, midnights[d], buckets[d]) for d in sorted(buckets)]


def _daily_entry(date_str: str, midnight_ts: int, items: list[dict[str, Any]]) -> dict[str, Any]:
    temps = [_safe_float(e.get("temperature")) for e in items if e.get("temperature") is not None]
    t_max, t_min, t_avg = _agg_max_min_avg(temps)

    hums_pct = [_safe_float(e.get("humidity")) for e in items if e.get("humidity") is not None]
    hums = [v / 100.0 for v in hums_pct]
    h_max, h_min, h_avg = _agg_max_min_avg(hums)

    winds = [_safe_float(e.get("wind_speed")) for e in items if e.get("wind_speed") is not None]
    w_max, w_min, w_avg = _agg_max_min_avg(winds)

    bearings = [e.get("wind_bearing") for e in items if e.get("wind_bearing") is not None]
    avg_bearing: float | None = None
    if bearings:
        avg_bearing = sum(_safe_float(b) for b in bearings) / len(bearings)

    day_items = [e for e in items if not _is_hourly_night(e)]
    night_items = [e for e in items if _is_hourly_night(e)]
    day_skycon = _condition_to_skycon(_most_common(e.get("condition") for e in day_items))
    night_skycon = _condition_to_skycon(
        _most_common(e.get("condition") for e in night_items), is_night=True
    )
    overall_skycon = _condition_to_skycon(_most_common(e.get("condition") for e in items))

    out: dict[str, Any] = {
        "date": date_str,
        "timestamp": midnight_ts,
        "skycon": {
            "datetime": date_str,
            "value": overall_skycon,
            "day": day_skycon,
            "night": night_skycon,
        },
        "wind": {
            "datetime": date_str,
            "speed": w_avg,
            "max": w_max,
            "min": w_min,
            "avg": w_avg,
        },
        "temperature": {
            "date": date_str,
            "timestamp": midnight_ts,
            "max": t_max,
            "min": t_min,
            "avg": t_avg,
        },
        "humidity": {
            "date": date_str,
            "timestamp": midnight_ts,
            "max": round(h_max, 4),
            "min": round(h_min, 4),
            "avg": round(h_avg, 4),
        },
        "pm25": {"date": date_str, "max": 0, "min": 0, "avg": 0},
    }
    octant = _bearing_to_octant16(avg_bearing)
    if octant is not None:
        out["wind"]["wind_dir"] = octant
        out["wind"]["wind_level"] = _wind_level_from_speed_kmh(w_avg)
    return out


def _is_hourly_night(entry: dict[str, Any]) -> bool:
    dt = _parse_dt(entry.get("datetime"))
    if dt is None:
        return False
    return _is_night_hour(dt.hour)


async def build_daily_weather_forecast(
    hass: HomeAssistant, weather_entity_id: str
) -> list[dict[str, Any]]:
    """Aggregate the entity's hourly forecast into per-day entries.

    HA-YandexWeather only advertises FORECAST_HOURLY (~48h), which yields
    2 daily entries. Aggregation gives correct max/min/avg per day instead
    of trusting whatever the entity exposes via twice_daily.
    """
    hourly_raw = await _fetch_forecast(hass, weather_entity_id, "hourly")
    if not hourly_raw:
        return []
    return [
        _daily_entry(date_str, ts, items)
        for date_str, ts, items in _daily_buckets(hourly_raw)
    ]


# ---------------------------------------------------------------------------
# Misc utility endpoints upstream actually serves
# ---------------------------------------------------------------------------


def build_server_now() -> dict[str, Any]:
    """Body for /daily/now: server time string + unix ts. Matches upstream format."""
    now = dt_util.now()
    return {
        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "timestamp": int(now.timestamp()),
    }
