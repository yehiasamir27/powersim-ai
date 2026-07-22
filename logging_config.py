"""
Structured logging configuration for PowerSim AI.

Provides a single ``setup_logging`` entry point that configures the root logger
with either a human-friendly console formatter (development) or line-delimited
JSON (production / log aggregation). Application code should obtain loggers via
``get_logger(__name__)`` and never call ``print``.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED_LOGRECORD_ATTRS = set(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render log records as single-line JSON for machine ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        # Merge any structured `extra=` fields passed by the caller.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOGRECORD_ATTRS and not key.startswith("_"):
                payload[key] = value

        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Compact, readable formatter for local development."""

    _COLORS = {
        "DEBUG": "\033[38;5;244m",
        "INFO": "\033[38;5;39m",
        "WARNING": "\033[38;5;214m",
        "ERROR": "\033[38;5;196m",
        "CRITICAL": "\033[48;5;196m\033[38;5;231m",
    }
    _RESET = "\033[0m"

    def __init__(self, use_color: bool = True) -> None:
        super().__init__()
        self.use_color = use_color and sys.stderr.isatty()

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created).strftime("%H:%M:%S")
        level = record.levelname
        if self.use_color:
            colour = self._COLORS.get(level, "")
            level = f"{colour}{level:<8}{self._RESET}"
        else:
            level = f"{level:<8}"
        base = f"{ts} {level} {record.name:<22} {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging(level: str = "INFO", json_logs: bool = False) -> None:
    """Configure the root logger.

    Args:
        level: Minimum log level (e.g. ``"INFO"``).
        json_logs: If ``True`` emit JSON lines; otherwise a console format.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    # Reset handlers so repeated calls (e.g. under --reload) don't duplicate.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if json_logs else ConsoleFormatter())
    root.addHandler(handler)

    # Tame noisy third-party loggers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module-scoped logger."""
    return logging.getLogger(name)
