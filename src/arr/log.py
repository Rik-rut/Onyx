from __future__ import annotations

import logging
import sys

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


def configure_logging(config: Config | None = None, level: int = logging.INFO) -> None:
    global _configured
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("arr")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    secrets: list[str] = []
    if config is not None:
        for k in SECRET_KEYS:
            v = config.get(k)
            if isinstance(v, str) and v:
                secrets.append(v)
    root.addFilter(_RedactFilter(secrets))
    _configured = True


def get_logger(name: str) -> logging.Logger:
    if not _configured:
        configure_logging()
    return logging.getLogger(f"arr.{name}")
