"""HTTP views that imitate the Qinping cloud endpoints.

Registered on Home Assistant's existing HTTP server. TLS is expected to be
terminated by an upstream reverse proxy (e.g. the NGINX Proxy add-on with a
customize.servers block matching `qing.cleargrass.com`).

Endpoint shapes are based on:
- ea/cgs2_decloud weather_server.py for /daily/weatherNow, /daily/locate,
  /device/pairStatus, /cooperation/companies, /firmware/checkUpdate;
- reverse-engineered LocationAPI::request{Weather,AQI}{FD,FH}List paths for
  /daily/dailyForecasts and /daily/hourlyForecasts (top-level QJsonArray
  response, dispatched by the `metric` query parameter).

Each view reads live options from hass.data on every request so an
options-flow update takes effect without re-registering routes.
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .transformer import (
    build_aqi_forecast_placeholder,
    build_payloads,
    build_weather_forecast,
)


class _QinpingViewBase(HomeAssistantView):
    requires_auth = False
    cors_allowed = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    @property
    def _options(self) -> dict[str, Any]:
        return self._hass.data[DOMAIN]["options"]


class QinpingLocateView(_QinpingViewBase):
    url = "/daily/locate"
    name = "qinping:locate"

    async def get(self, request: web.Request) -> web.Response:
        _, location = build_payloads(self._hass, **self._options)
        return web.json_response({"data": location, "code": 0})


class QinpingWeatherNowView(_QinpingViewBase):
    url = "/daily/weatherNow"
    name = "qinping:weather_now"

    async def get(self, request: web.Request) -> web.Response:
        weather, _ = build_payloads(self._hass, **self._options)
        return web.json_response({"code": 0, "data": weather})


class _QinpingForecastView(_QinpingViewBase):
    forecast_type: str = ""

    async def get(self, request: web.Request) -> web.Response:
        metric = request.query.get("metric", "weather")
        if metric == "weather":
            options = self._options
            data = await build_weather_forecast(
                self._hass,
                options["weather_entity_id"],
                self.forecast_type,
                uv_sensor=options.get("uv_sensor"),
            )
        else:  # aqi or aqi_us
            data = build_aqi_forecast_placeholder()
        return web.json_response(data)


class QinpingDailyForecastsView(_QinpingForecastView):
    url = "/daily/dailyForecasts"
    name = "qinping:daily_forecasts"
    forecast_type = "daily"


class QinpingHourlyForecastsView(_QinpingForecastView):
    url = "/daily/hourlyForecasts"
    name = "qinping:hourly_forecasts"
    forecast_type = "hourly"


class QinpingPairStatusView(_QinpingViewBase):
    url = "/device/pairStatus"
    name = "qinping:pair_status"

    async def get(self, request: web.Request) -> web.Response:
        return web.json_response({"desc": "ok", "code": 10503})


class QinpingCooperationView(_QinpingViewBase):
    url = "/cooperation/companies"
    name = "qinping:cooperation"

    async def get(self, request: web.Request) -> web.Response:
        return web.json_response({"data": {"cooperation": ["private"]}, "code": 1})


class QinpingFirmwareView(_QinpingViewBase):
    url = "/firmware/checkUpdate"
    name = "qinping:firmware"

    async def get(self, request: web.Request) -> web.Response:
        return web.json_response({"data": {"upgrade_sign": 0}, "code": 0})


ALL_VIEW_CLASSES: tuple[type[_QinpingViewBase], ...] = (
    QinpingLocateView,
    QinpingWeatherNowView,
    QinpingDailyForecastsView,
    QinpingHourlyForecastsView,
    QinpingPairStatusView,
    QinpingCooperationView,
    QinpingFirmwareView,
)
