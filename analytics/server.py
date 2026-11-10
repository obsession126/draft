"""Local HTTP and Server-Sent Events API for the analytics demo."""

from __future__ import annotations

import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from analytics.engine import AnalyticsEngine

LOGGER = logging.getLogger("analytics.server")
DEFAULT_ALLOWED_ORIGINS = (
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


class AnalyticsHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        engine: AnalyticsEngine,
        allowed_origins: tuple[str, ...] = DEFAULT_ALLOWED_ORIGINS,
    ) -> None:
        self.engine = engine
        self.allowed_origins = allowed_origins
        super().__init__(address, AnalyticsRequestHandler)


class AnalyticsRequestHandler(BaseHTTPRequestHandler):
    server: AnalyticsHTTPServer
    protocol_version = "HTTP/1.1"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Last-Event-ID")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/healthz":
            self._send_json({"status": "ok"})
            return
        if parsed.path == "/api/v1/snapshot":
            self._send_json(self.server.engine.snapshot())
            return
        if parsed.path == "/api/v1/history":
            query = parse_qs(parsed.query)
            limit_value = query.get("limit", ["100"])[0]
            try:
                limit = int(limit_value)
            except ValueError:
                self._send_json({"error": "limit must be an integer."}, status=400)
                return
            self._send_json(self.server.engine.history(limit))
            return
        if parsed.path == "/api/v1/stream":
            self._stream_events()
            return
        self._send_json({"error": "Not found."}, status=404)

    def log_message(self, format_string: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format_string % args)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _stream_events(self) -> None:
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_event_id = self.headers.get("Last-Event-ID")
        try:
            while True:
                event = self.server.engine.wait_for_event(last_event_id)
                if event is None:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    continue
                encoded = json.dumps(
                    event,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
                self.wfile.write(
                    b"id: "
                    + event["event_id"].encode("ascii")
                    + b"\nevent: telemetry\ndata: "
                    + encoded
                    + b"\n\n"
                )
                self.wfile.flush()
                last_event_id = event["event_id"]
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            LOGGER.info("SSE client disconnected.")

    def _send_cors_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in self.server.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")


def allowed_origins_from_environment() -> tuple[str, ...]:
    configured = os.environ.get("ANALYTICS_CORS_ORIGINS")
    if configured is None:
        return DEFAULT_ALLOWED_ORIGINS
    origins = tuple(origin.strip() for origin in configured.split(",") if origin.strip())
    if not origins:
        raise ValueError("ANALYTICS_CORS_ORIGINS must contain at least one origin.")
    return origins
