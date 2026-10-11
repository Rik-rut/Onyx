from __future__ import annotations

import io
import logging
from pathlib import Path

from starlette.testclient import TestClient

from arr.config.settings import DEFAULTS, Config
from arr.log import configure_logging, get_logger
from arr.web.app import create_app


def test_configure_logging_format_and_redaction() -> None:
    stream = io.StringIO()
    cfg = Config(values=dict(DEFAULTS))
    cfg.values["transmission_rpc_pass"] = "SuperSecretPassword123"

    configure_logging(cfg, level=logging.INFO, stream=stream)
    log = get_logger("test")
    log.info("Connecting with password SuperSecretPassword123 now")

    output = stream.getvalue()
    assert "[INFO ] [arr.test] Connecting with password ***redacted*** now" in output
    assert output.startswith("[")


def test_http_request_logging_middleware(tmp_path: Path) -> None:
    stream = io.StringIO()
    vals = dict(DEFAULTS)
    vals["download_root"] = str(tmp_path / "downloads")
    vals["library_root"] = str(tmp_path / "downloads")
    cfg = Config(values=vals)

    configure_logging(cfg, level=logging.INFO, stream=stream)
    app = create_app(cfg)
    client = TestClient(app)

    # 1. API request should be logged
    client.get("/api/queue")
    output = stream.getvalue()
    assert "GET /api/queue -> 200" in output

    # 2. Static asset requests should be omitted to avoid console noise
    stream.truncate(0)
    stream.seek(0)
    client.get("/static/index.html")
    static_output = stream.getvalue()
    assert "GET /static/index.html" not in static_output
