"""HTTP views that imitate the Qinping cloud endpoints.

These are registered on Home Assistant's existing HTTP server. TLS is expected
to be terminated by an upstream reverse proxy (e.g. the NGINX Proxy add-on with
a customize.servers block matching `qing.cleargrass.com`).

Each view reads the current option dict from hass.data on every request so an
options-flow update takes effect without re-registering routes (HA HTTP has no
public unregister API).
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .transformer import build_payloads


class _QinpingViewBase(HomeAssistantView):
    requires_auth = False
    cors_allowed = True

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    def _build(self) -> tuple[dict[str, Any], dict[str, Any]]:
        options: dict[str, Any] = self._hass.data[DOMAIN]["options"]
        return build_payloads(self._hass, **options)


class QinpingLocateView(_QinpingViewBase):
    url = "/daily/locate"
    name = "qinping:locate"

    async def get(self, request: web.Request) -> web.Response:
        _, location = self._build()
        return web.json_response({"data": location, "code": 0})


class QinpingWeatherNowView(_QinpingViewBase):
    url = "/daily/weatherNow"
    name = "qinping:weather_now"

    async def get(self, request: web.Request) -> web.Response:
        weather, _ = self._build()
        return web.json_response({"code": 0, "data": weather})


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
    QinpingPairStatusView,
    QinpingCooperationView,
    QinpingFirmwareView,
)
