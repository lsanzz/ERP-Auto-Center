"""Structured application logs, request correlation and operational probes."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from uuid import uuid4

from flask import Flask, g, request


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_observability(app: Flask) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    app.logger.handlers.clear()
    app.logger.addHandler(handler)
    app.logger.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    @app.before_request
    def begin_request():
        incoming = request.headers.get("X-Request-ID", "")[:64]
        g.request_id = incoming if incoming.replace("-", "").isalnum() else uuid4().hex
        g.request_started_at = time.perf_counter()

    @app.after_request
    def complete_request(response):
        response.headers["X-Request-ID"] = getattr(g, "request_id", uuid4().hex)
        duration = round((time.perf_counter() - getattr(g, "request_started_at", time.perf_counter())) * 1000, 2)
        app.logger.info(
            "request_completed",
            extra={
                "request_id": response.headers["X-Request-ID"],
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration,
            },
        )
        return response

    @app.teardown_request
    def log_unhandled_exception(error):
        if error is not None:
            app.logger.exception(
                "request_failed",
                exc_info=error,
                extra={"request_id": getattr(g, "request_id", None), "method": request.method, "path": request.path},
            )
