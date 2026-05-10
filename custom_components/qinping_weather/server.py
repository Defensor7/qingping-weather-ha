"""HTTPS server that imitates the Qinping cloud endpoints.

Endpoints are kept byte-compatible with ea/cgs2_decloud's weather_server.py so
existing /etc/hosts redirection on the device works unchanged.
"""
from __future__ import annotations

import json
import logging
import ssl
from typing import Any

from aiohttp import web

from homeassistant.core import HomeAssistant

from .transformer import build_payloads

_LOGGER = logging.getLogger(__name__)


class QinpingServer:
    def __init__(
        self,
        hass: HomeAssistant,
        *,
        bind_host: str,
        port: int,
        weather_entity: str,
        station_name: str,
        city_id: str,
        timezone: str,
        ssl_certificate: str,
        ssl_key: str,
    ) -> None:
        self._hass = hass
        self._bind_host = bind_host
        self._port = port
        self._weather_entity = weather_entity
        self._station_name = station_name
        self._city_id = city_id
        self._timezone = timezone
        self._ssl_certificate = ssl_certificate
        self._ssl_key = ssl_key

        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/daily/locate", self._handle_locate)
        app.router.add_get("/daily/weatherNow", self._handle_weather)
        app.router.add_get("/device/pairStatus", self._handle_pair_status)
        app.router.add_get("/cooperation/companies", self._handle_cooperation)
        app.router.add_get("/firmware/checkUpdate", self._handle_firmware)
        app.router.add_route("*", "/{tail:.*}", self._handle_fallback)

        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # Loading is blocking; do it in executor to keep the event loop clean.
        await self._hass.async_add_executor_job(
            ssl_context.load_cert_chain, self._ssl_certificate, self._ssl_key
        )

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(
            self._runner,
            host=self._bind_host,
            port=self._port,
            ssl_context=ssl_context,
        )
        await self._site.start()
        _LOGGER.info(
            "Qinping weather server listening on https://%s:%s (source: %s)",
            self._bind_host,
            self._port,
            self._weather_entity,
        )

    async def stop(self) -> None:
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def _build(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return build_payloads(
            self._hass,
            self._weather_entity,
            station_name=self._station_name,
            city_id=self._city_id,
            timezone=self._timezone,
        )

    @staticmethod
    def _json_response(payload: dict[str, Any]) -> web.Response:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        return web.Response(
            body=body,
            content_type="application/json",
            charset="utf-8",
            headers={
                "Connection": "keep-alive",
                "Vary": "Accept-Encoding",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            },
        )

    async def _handle_locate(self, request: web.Request) -> web.Response:
        _, location = self._build()
        return self._json_response({"data": location, "code": 0})

    async def _handle_weather(self, request: web.Request) -> web.Response:
        weather, _ = self._build()
        return self._json_response({"code": 0, "data": weather})

    async def _handle_pair_status(self, request: web.Request) -> web.Response:
        return self._json_response({"desc": "ok", "code": 10503})

    async def _handle_cooperation(self, request: web.Request) -> web.Response:
        return self._json_response({"data": {"cooperation": ["private"]}, "code": 1})

    async def _handle_firmware(self, request: web.Request) -> web.Response:
        return self._json_response({"data": {"upgrade_sign": 0}, "code": 0})

    async def _handle_fallback(self, request: web.Request) -> web.Response:
        _LOGGER.debug("Unhandled Qinping request: %s %s", request.method, request.path)
        return web.json_response(
            {"error": "Not Found", "path": request.path}, status=404
        )
