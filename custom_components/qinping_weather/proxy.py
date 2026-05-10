"""Forward incoming Qinping requests to the real qing.cleargrass.com.

Uses HA's shared aiohttp ClientSession (with proper TLS roots). Headers from
the device are passed through verbatim — including `app-sign`, `app-timestamp`
and `device-sn` — so the upstream signature check stays valid. We strip
hop-by-hop headers and force `Accept-Encoding: identity` so the response body
is plain JSON we don't have to decompress.
"""
from __future__ import annotations

import logging

from aiohttp import ClientError, ClientTimeout, web

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

UPSTREAM_BASE = "https://qing.cleargrass.com"
UPSTREAM_HOST = "qing.cleargrass.com"

_REQ_STRIP = {
    "host",
    "content-length",
    "connection",
    "accept-encoding",
    "transfer-encoding",
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
}

_RESP_STRIP = {
    "content-encoding",
    "transfer-encoding",
    "connection",
    "content-length",
    "keep-alive",
}


async def proxy_request(hass: HomeAssistant, request: web.Request) -> web.Response:
    """Forward `request` to the real upstream and return its response."""
    session = async_get_clientsession(hass)
    url = f"{UPSTREAM_BASE}{request.rel_url}"
    body = await request.read()

    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _REQ_STRIP
    }
    headers["Host"] = UPSTREAM_HOST
    headers["Accept-Encoding"] = "identity"

    try:
        async with session.request(
            request.method,
            url,
            headers=headers,
            data=body if body else None,
            timeout=ClientTimeout(total=20),
            allow_redirects=False,
        ) as upstream:
            payload = await upstream.read()
            _LOGGER.debug(
                "proxy %s %s -> %s (%dB)",
                request.method,
                request.rel_url,
                upstream.status,
                len(payload),
            )
            response_headers = {
                k: v
                for k, v in upstream.headers.items()
                if k.lower() not in _RESP_STRIP
            }
            return web.Response(
                body=payload,
                status=upstream.status,
                headers=response_headers,
            )
    except ClientError as err:
        _LOGGER.warning("proxy upstream error for %s: %s", request.rel_url, err)
        return web.json_response(
            {"error": "upstream_failed", "detail": str(err)}, status=502
        )
