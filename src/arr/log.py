from __future__ import annotations

import logging
import sys
from typing import Any

from arr.config.settings import SECRET_KEYS, Config

_configured = False


class _RedactFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for s in self._secrets:
            msg = msg.replace(s, "***redacted***")
        record.msg = msg
        record.args = ()
        return True


def configure_logging(
    config: Config | None = None,
    level: int = logging.INFO,
    stream: Any = None,
) -> None:
    global _configured
    handler = logging.StreamHandler(stream or sys.stdout)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

    secrets: list[str] = []
    if config is not None:
        for k in SECRET_KEYS:
            v = config.get(k)
            if isinstance(v, str) and v:
                secrets.append(v)
    redact_filter = _RedactFilter(secrets)
    handler.addFilter(redact_filter)

    root = logging.getLogger("arr")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    root.addFilter(redact_filter)

    # Format uvicorn loggers so HTTP requests and server status are visible
    for uvi_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvi = logging.getLogger(uvi_name)
        uvi.setLevel(level)
        if not uvi.handlers:
            uvi.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(f"arr.{name}")
