"""Constants for the Qinping Local Weather integration."""
from __future__ import annotations

DOMAIN = "qinping_weather"

CONF_WEATHER_ENTITY = "weather_entity"
CONF_STATION_NAME = "station_name"
CONF_CITY_ID = "city_id"
CONF_TIMEZONE = "timezone"

CONF_UV_SENSOR = "uv_sensor"
CONF_AQI_SENSOR = "aqi_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_PM25_SENSOR = "pm25_sensor"
CONF_PM10_SENSOR = "pm10_sensor"

CONF_PROXY_MODE = "proxy_mode"
CONF_FORWARD_FIRMWARE_CHECK = "forward_firmware_check"

DEFAULT_STATION_NAME = "Home"
DEFAULT_CITY_ID = "n000000"

OPTIONAL_SENSOR_KEYS: tuple[str, ...] = (
    CONF_UV_SENSOR,
    CONF_AQI_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_PM25_SENSOR,
    CONF_PM10_SENSOR,
)
