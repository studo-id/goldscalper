"""Structured logging with secret redaction.

Emits JSON logs (optionally console-formatted in debug) while guaranteeing
that credentials never reach the log stream.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from config.settings import settings

try:  # pragma: no cover - optional dependency
    from pythonjsonlogger import json as jsonlogger

    _HAS_JSON = True
except Exception:  # pragma: no cover
    _HAS_JSON = False


_REDACT_KEYS = {
    "password",
    "passwd",
    "token",
    "api_token",
    "mt5_password",
    "telegram_bot_token",
    "redis_password",
    "secret",
    "authorization",
}

# Patterns for values that must never be logged regardless of key name.
_SECRET_PATTERNS = [
    re.compile(r"(?i)(password|passwd|token|secret|bearer)\s*[=:]\s*\S+"),
]


class RedactionFilter(logging.Filter):
    """Scrub credentials from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        for pattern in _SECRET_PATTERNS:
            message = pattern.sub(r"\1=***REDACTED***", message)
        record.msg = message
        record.args = ()

        for key in list(getattr(record, "__dict__", {}).keys()):
            if key.lower() in _REDACT_KEYS:
                setattr(record, key, "***REDACTED***")
        return True


def _build_formatter() -> logging.Formatter:
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"
    if _HAS_JSON and not settings.debug:
        return jsonlogger.JsonFormatter(
            fmt,
            rename_fields={"asctime": "ts", "levelname": "level", "name": "logger"},
        )
    return logging.Formatter(fmt)


def configure_logging(level: int | None = None) -> None:
    """Configure root logging once at startup."""
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_build_formatter())
    handler.addFilter(RedactionFilter())

    root.addHandler(handler)
    root.setLevel(level or (logging.DEBUG if settings.debug else logging.INFO))

    # Quiet noisy third-party loggers.
    for noisy in ("uvicorn.access", "asyncio", "asyncpg", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger."""
    return logging.getLogger(name)


def log_kv(logger: logging.Logger, msg: str, **kwargs: Any) -> None:
    """Log a message with structured (redaction-safe) key/value context."""
    safe = {k: ("***REDACTED***" if k.lower() in _REDACT_KEYS else v) for k, v in kwargs.items()}
    logger.info("%s | %s", msg, " ".join(f"{k}={v}" for k, v in safe.items()))
