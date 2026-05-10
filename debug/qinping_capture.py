#!/usr/bin/env python3
"""Standalone HTTPS sniffer for QingPing CGS2 cloud traffic.

Run on a host the device can reach (point `/etc/hosts` on the device to its
IP for `qing.cleargrass.com` and friends). Logs every request — method, path,
query, headers, body — and replies with plausible JSON so the device keeps
polling and reveals the full set of paths it touches.

Usage:
    sudo python3 debug/qinping_capture.py             # listen on 0.0.0.0:443
    sudo python3 debug/qinping_capture.py --port 4443

Cert + key are auto-generated next to this script the first time it runs.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM_HOST = "qing.cleargrass.com"

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CERTFILE = os.path.join(HERE, "cert.pem")
DEFAULT_KEYFILE = os.path.join(HERE, "key.pem")

_print_lock = threading.Lock()


def ensure_cert(certfile: str, keyfile: str) -> None:
    if os.path.isfile(certfile) and os.path.isfile(keyfile):
        return
    print(f"[setup] generating self-signed cert -> {certfile}, {keyfile}")
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            keyfile,
            "-out",
            certfile,
            "-days",
            "3650",
            "-nodes",
            "-subj",
            "/CN=qing.cleargrass.com",
        ],
        check=True,
    )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_request(handler: "Handler", body: bytes) -> None:
    lines: list[str] = []
    lines.append(f"\n=== {_now()} ===")
    lines.append(f">>> {handler.command} {handler.path}")
    lines.append(f"    from {handler.client_address[0]}:{handler.client_address[1]}")
    for header_name, header_value in handler.headers.items():
        lines.append(f"    {header_name}: {header_value}")
    if body:
        try:
            decoded = body.decode("utf-8")
            lines.append(f"    body ({len(body)}B): {decoded}")
        except UnicodeDecodeError:
            lines.append(f"    body ({len(body)}B, binary): {body!r}")
    else:
        lines.append("    body: <none>")
    with _print_lock:
        print("\n".join(lines), flush=True)


def _log_response(handler: "Handler", status: int, payload: bytes) -> None:
    with _print_lock:
        try:
            preview = payload.decode("utf-8")
        except UnicodeDecodeError:
            preview = repr(payload)
        if len(preview) > 800:
            preview = preview[:800] + "...<truncated>"
        print(
            f"<<< {status} {HTTPStatus(status).phrase} ({len(payload)}B)\n    {preview}",
            flush=True,
        )


# Minimal canned responses — enough to keep the device polling.
_now_payload = {
    "city": {
        "city": "Capture",
        "cityId": "n000000",
        "cnAddress": {"city": "", "cityId": "n000000", "country": "", "province": ""},
        "cnCity": "",
        "country": "",
        "enAddress": {"city": "Capture", "cityId": "n000000", "country": "", "province": ""},
        "latitude": "0.0",
        "longitude": "0.0",
        "name": "Capture",
        "name_cn": "",
        "name_cn_tw": "",
        "name_en": "Capture",
        "province": "",
        "timezone": "UTC",
        "timezoneFmt": "UTC",
    },
    "city_id": "n000000",
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
        "humidity": 50,
        "probability": 0,
        "pub_time": 0,
        "skycon": "CLEAR_DAY",
        "temp_max": 20,
        "temp_min": 10,
        "temperature": 15,
        "ultraviolet": 0,
        "vehicle_limit": {"type": "city_unlimited"},
        "wind": {"speed": 0, "wind_dir": "N", "wind_level": 0},
    },
}

_locate_payload = {
    "city_id": "n000000",
    "name": "Capture",
    "name_cn": "",
    "name_en": "Capture",
    "country": "",
}


def _forecast_weather_array(n_entries: int, step_seconds: int) -> list[dict]:
    base = int(time.time())
    return [
        {
            "date": base + i * step_seconds,
            "skycon": "CLEAR_DAY",
            "temp_max": 20,
            "temp_min": 10,
            "humidity": 50,
            "probability": 0,
            "ultraviolet": 0,
            "aqi": 0,
            "aqi_us": 0,
            "noAqi": True,
            "pm10": 0,
            "pm25": 0,
            "wind": {"speed": 0, "wind_dir": "N", "wind_level": 0},
        }
        for i in range(n_entries)
    ]


def _proxy_upstream(
    method: str,
    full_path: str,
    headers: dict[str, str],
    body: bytes,
) -> tuple[int, dict[str, str], bytes]:
    """Forward request to the real qing.cleargrass.com 1:1. Returns
    (status, response_headers, body_bytes). Strips Accept-Encoding so the
    upstream gives us plain JSON we can log directly."""
    fwd = {k: v for k, v in headers.items()
           if k.lower() not in ("host", "content-length", "accept-encoding", "connection")}
    fwd["Host"] = UPSTREAM_HOST
    fwd["Accept-Encoding"] = "identity"

    ctx = ssl.create_default_context()
    conn = http.client.HTTPSConnection(UPSTREAM_HOST, 443, timeout=20, context=ctx)
    try:
        conn.request(method, full_path, body=body if body else None, headers=fwd)
        resp = conn.getresponse()
        status = resp.status
        resp_headers = {k: v for k, v in resp.getheaders()}
        raw = resp.read()
        return status, resp_headers, raw
    finally:
        conn.close()


def _route(path: str, query: str) -> tuple[int, dict | list]:
    """Return (status, json_payload) for a request path."""
    if path == "/daily/locate":
        return 200, {"data": _locate_payload, "code": 0}
    if path == "/daily/weatherNow":
        return 200, {"code": 0, "data": {**_now_payload, "weather": {**_now_payload["weather"], "pub_time": int(time.time())}}}
    if path == "/daily/dailyForecasts":
        # Top-level array per RE notes
        if "metric=aqi" in query:
            return 200, []
        return 200, _forecast_weather_array(7)
    if path == "/daily/hourlyForecasts":
        if "metric=aqi" in query:
            return 200, []
        return 200, _forecast_weather_array(24)
    if path == "/device/pairStatus":
        return 200, {"desc": "ok", "code": 10503}
    if path.startswith("/cooperation/companies"):
        return 200, {"data": {"cooperation": ["private"]}, "code": 1}
    if path.startswith("/firmware/checkUpdate"):
        return 200, {"data": {"upgrade_sign": 0}, "code": 0}
    return 404, {"error": "not_found", "path": path}


class Handler(BaseHTTPRequestHandler):
    proxy_mode: bool = False

    # Suppress default per-request log line — we have our own.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _handle(self) -> None:
        body = self._read_body()
        _log_request(self, body)

        if self.proxy_mode:
            try:
                status, upstream_headers, body_bytes = _proxy_upstream(
                    self.command,
                    self.path,
                    {k: v for k, v in self.headers.items()},
                    body,
                )
            except Exception as err:
                with _print_lock:
                    print(f"[proxy] upstream error: {err}", flush=True)
                status = 502
                body_bytes = json.dumps(
                    {"error": "upstream_failed", "detail": str(err)}
                ).encode("utf-8")
                upstream_headers = {"Content-Type": "application/json; charset=utf-8"}

            self.send_response(status)
            for h, v in upstream_headers.items():
                if h.lower() in (
                    "transfer-encoding",
                    "content-encoding",
                    "connection",
                    "content-length",
                ):
                    continue
                self.send_header(h, v)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            self.wfile.write(body_bytes)
            _log_response(self, status, body_bytes)
            return

        path, _, query = self.path.partition("?")
        status, payload = _route(path, query)
        body_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.wfile.write(body_bytes)

        _log_response(self, status, body_bytes)

    do_GET = _handle
    do_POST = _handle
    do_PUT = _handle
    do_DELETE = _handle
    do_PATCH = _handle
    do_HEAD = _handle


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=443)
    parser.add_argument("--certfile", default=DEFAULT_CERTFILE)
    parser.add_argument("--keyfile", default=DEFAULT_KEYFILE)
    parser.add_argument(
        "--proxy",
        action="store_true",
        help="MITM mode: forward each request 1:1 to the real qing.cleargrass.com "
        "and return the upstream response to the device (signing stays valid).",
    )
    args = parser.parse_args()

    Handler.proxy_mode = args.proxy
    if args.proxy:
        print("[mode] PROXY -> real https://qing.cleargrass.com", flush=True)
    else:
        print("[mode] STUB (canned responses)", flush=True)

    ensure_cert(args.certfile, args.keyfile)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=args.certfile, keyfile=args.keyfile)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    print(f"[ready] https://{args.host}:{args.port} (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[bye]")
    server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
