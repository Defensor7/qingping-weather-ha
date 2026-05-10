"""Forward incoming Qinping requests to the real qing.cleargrass.com.

Uses HA's shared aiohttp ClientSession (with proper TLS roots). Headers from
the device are passed through verbatim — including `app-sign`, `app-timestamp`
and `device-sn` — so the upstream signature check stays valid. We strip
hop-by-hop headers and force `Accept-Encoding: identity` so the response body
is plain JSON we don't have to decompress.
"""
from __future__ import annotations

import logging
import time

from aiohttp import ClientError, ClientTimeout, web

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

UPSTREAM_BASE = "https://qing.cleargrass.com"
UPSTREAM_HOST = "qing.cleargrass.com"

# Headers we never forward upstream (hop-by-hop or HA-injected proxy hints).
# Note `host` is excluded so aiohttp can set it itself from the URL — setting
# it explicitly causes some aiohttp versions to complain.
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

_BODY_PREVIEW = 16000


def _redact(headers: dict[str, str]) -> dict[str, str]:
    out = {}
    for k, v in headers.items():
        if k.lower() in ("app-sign",):
            out[k] = (v[:6] + "…") if v else v
        else:
            out[k] = v
    return out


async def proxy_request(hass: HomeAssistant, request: web.Request) -> web.Response:
    """Forward `request` to the real upstream and return its response."""
    session = async_get_clientsession(hass)
    url = f"{UPSTREAM_BASE}{request.rel_url}"
    body = await request.read()

    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in _REQ_STRIP
    }
    headers["Accept-Encoding"] = "identity"

    _LOGGER.info(
        "proxy -> %s %s%s (body %dB)",
        request.method,
        UPSTREAM_HOST,
        request.rel_url,
        len(body),
    )
    if _LOGGER.isEnabledFor(logging.DEBUG):
        _LOGGER.debug("proxy req headers: %s", _redact(headers))
        if body:
            preview = body[:_BODY_PREVIEW]
            try:
                preview_str = preview.decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover
                preview_str = repr(preview)
            _LOGGER.debug("proxy req body preview: %s", preview_str)

    started = time.monotonic()
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
            elapsed_ms = int((time.monotonic() - started) * 1000)
            _LOGGER.info(
                "proxy <- %s %d (%dB, %dms) for %s",
                request.method,
                upstream.status,
                len(payload),
                elapsed_ms,
                request.rel_url,
            )
            if _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "proxy resp headers: %s", dict(upstream.headers)
                )
                preview = payload[:_BODY_PREVIEW]
                try:
                    preview_str = preview.decode("utf-8", errors="replace")
                except Exception:  # pragma: no cover
                    preview_str = repr(preview)
                _LOGGER.debug("proxy resp body preview: %s", preview_str)

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
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _LOGGER.warning(
            "proxy upstream error after %dms for %s %s: %s: %s",
            elapsed_ms,
            request.method,
            request.rel_url,
            type(err).__name__,
            err,
        )
        return web.json_response(
            {"error": "upstream_failed", "detail": f"{type(err).__name__}: {err}"},
            status=502,
        )
    except Exception as err:  # pragma: no cover - last resort
        elapsed_ms = int((time.monotonic() - started) * 1000)
        _LOGGER.exception(
            "proxy unexpected error after %dms for %s %s",
            elapsed_ms,
            request.method,
            request.rel_url,
        )
        return web.json_response(
            {"error": "proxy_internal", "detail": f"{type(err).__name__}: {err}"},
            status=502,
        )


def log_local_dispatch(view_name: str, request: web.Request) -> None:
    """Log a local-render dispatch (called from views when proxy_mode is off)."""
    _LOGGER.debug("local %s %s%s", request.method, view_name, request.rel_url)


def log_local_response(view_name: str, response: web.Response) -> None:
    """Dump body of a locally-rendered response when DEBUG is enabled."""
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return
    body = response.body
    if isinstance(body, (bytes, bytearray)):
        size = len(body)
        try:
            preview = bytes(body[:_BODY_PREVIEW]).decode("utf-8")
        except UnicodeDecodeError:
            preview = repr(bytes(body[:_BODY_PREVIEW]))
    else:
        size = -1
        preview = str(body)[:_BODY_PREVIEW]
    _LOGGER.debug("local %s response (%dB): %s", view_name, size, preview)
