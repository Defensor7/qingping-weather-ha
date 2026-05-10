"""HTTP views that imitate the Qinping cloud endpoints.

Registered on Home Assistant's existing HTTP server. TLS is expected to be
terminated by an upstream reverse proxy (e.g. the NGINX Proxy add-on with a
customize.servers block matching `qing.cleargrass.com`).

Behavior flags read live from hass.data[DOMAIN]:

  proxy_mode             -> when True, every weather/AQI/locate/now/pair/
                            cooperation endpoint is forwarded 1:1 to the real
                            qing.cleargrass.com (signing stays valid since the
                            device's headers are passed through).
  forward_firmware_check -> when True, /firmware/checkUpdate is forwarded
                            (independent of proxy_mode). When False, returns
                            a stub "no update" response.
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .proxy import log_local_dispatch, proxy_request
from .transformer import (
    build_daily_weather_forecast,
    build_hourly_weather_forecast,
    build_payloads,
    build_server_now,
)


class _QinpingViewBase(HomeAssistantView):
    requires_auth = False
    cors_allowed = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    @property
    def _state(self) -> dict[str, Any]:
        return self._hass.data[DOMAIN]

    @property
    def _build_kwargs(self) -> dict[str, Any]:
        return self._state["build_kwargs"]

    @property
    def _proxy_all(self) -> bool:
        return bool(self._state.get("proxy_mode"))

    @property
    def _forward_firmware(self) -> bool:
        return bool(self._state.get("forward_firmware_check"))


class _ProxyableView(_QinpingViewBase):
    """Mixin: when proxy_mode is on, forward; otherwise call subclass _local."""

    async def get(self, request: web.Request) -> web.Response:
        if self._proxy_all:
            return await proxy_request(self._hass, request)
        log_local_dispatch(self.name, request)
        return await self._local(request)

    async def _local(self, request: web.Request) -> web.Response:  # pragma: no cover
        raise NotImplementedError


class QinpingLocateView(_ProxyableView):
    url = "/daily/locate"
    name = "qinping:locate"

    async def _local(self, request: web.Request) -> web.Response:
        _, location = build_payloads(self._hass, **self._build_kwargs)
        return web.json_response({"data": location, "code": 0})


class QinpingWeatherNowView(_ProxyableView):
    url = "/daily/weatherNow"
    name = "qinping:weather_now"

    async def _local(self, request: web.Request) -> web.Response:
        weather, _ = build_payloads(self._hass, **self._build_kwargs)
        return web.json_response({"code": 0, "data": weather})


class QinpingDailyForecastsView(_ProxyableView):
    url = "/daily/dailyForecasts"
    name = "qinping:daily_forecasts"

    async def _local(self, request: web.Request) -> web.Response:
        metric = request.query.get("metric", "weather")
        if metric == "weather":
            data = await build_daily_weather_forecast(
                self._hass, self._state["weather_entity_id"]
            )
        else:
            data = []
        return web.json_response({"code": 0, "data": data})


class QinpingHourlyForecastsView(_ProxyableView):
    url = "/daily/hourlyForecasts"
    name = "qinping:hourly_forecasts"

    async def _local(self, request: web.Request) -> web.Response:
        metric = request.query.get("metric", "weather")
        if metric == "weather":
            data = await build_hourly_weather_forecast(
                self._hass, self._state["weather_entity_id"]
            )
        else:
            data = []
        return web.json_response({"code": 0, "data": data})


class QinpingNowView(_ProxyableView):
    """/daily/now -> server time. Device polls this for clock sync."""
    url = "/daily/now"
    name = "qinping:now"

    async def _local(self, request: web.Request) -> web.Response:
        return web.json_response({"code": 0, "data": build_server_now()})


class QinpingPairStatusView(_ProxyableView):
    url = "/device/pairStatus"
    name = "qinping:pair_status"

    async def _local(self, request: web.Request) -> web.Response:
        return web.json_response({"desc": "ok", "code": 10503})


class QinpingCooperationView(_ProxyableView):
    url = "/cooperation/companies"
    name = "qinping:cooperation"

    async def _local(self, request: web.Request) -> web.Response:
        return web.json_response({"data": {"cooperation": ["private"]}, "code": 1})


class QinpingFirmwareView(_QinpingViewBase):
    """Firmware check is gated by its own flag, not proxy_mode."""
    url = "/firmware/checkUpdate"
    name = "qinping:firmware"

    async def get(self, request: web.Request) -> web.Response:
        if self._forward_firmware:
            return await proxy_request(self._hass, request)
        log_local_dispatch(self.name, request)
        return web.json_response({"data": {"upgrade_sign": 0}, "code": 0})


ALL_VIEW_CLASSES: tuple[type[_QinpingViewBase], ...] = (
    QinpingLocateView,
    QinpingWeatherNowView,
    QinpingDailyForecastsView,
    QinpingHourlyForecastsView,
    QinpingNowView,
    QinpingPairStatusView,
    QinpingCooperationView,
    QinpingFirmwareView,
)
