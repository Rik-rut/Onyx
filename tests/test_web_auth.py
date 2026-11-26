"""Web auth: login flow, session gating of API/WebSocket, and warnings.

Covers the web-auth spec end to end, including the full credential lifecycle:
unauthenticated status -> default login -> forced change -> authenticated
access -> logout -> 401 -> login with the new credentials.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from arr.config.settings import DEFAULTS, Config
from arr.web.app import create_app


@pytest.fixture
def web_app(tmp_path: Path):
    vals = dict(DEFAULTS)
    vals["download_root"] = str(tmp_path / "downloads")
    vals["library_root"] = str(tmp_path / "downloads")
    cfg = Config(values=vals)
    return create_app(cfg, auth_path=tmp_path / "auth.toml")


@pytest.fixture
def client(web_app) -> TestClient:
    with patch("arr.pipeline.ensure_daemon", return_value=None):
        yield TestClient(web_app)


@pytest.fixture
def fresh_app(tmp_path: Path):
    """A second app on its own auth file (fresh session store, same account file)."""

    def _make() -> TestClient:
        cfg = Config(values=dict(DEFAULTS))
        app = create_app(cfg, auth_path=tmp_path / "auth.toml")
        return TestClient(app)

    return _make


def _login(client: TestClient, username: str, password: str):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_status_unauthenticated(client: TestClient) -> None:
    resp = client.get("/api/auth/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is False
    assert body["username"] is None
    assert body["must_change_credentials"] is True


def test_login_invalid_returns_401_without_session(client: TestClient) -> None:
    resp = _login(client, "admin", "wrong")
    assert resp.status_code == 401
    assert "onyx_session" not in resp.headers.get("set-cookie", "")

    resp = _login(client, "nobody", "1234")
    assert resp.status_code == 401


def test_login_valid_sets_session_cookie(client: TestClient) -> None:
    resp = _login(client, "admin", "1234")
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "onyx_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    body = resp.json()
    assert body["authenticated"] is True
    assert body["username"] == "admin"
    assert body["must_change_credentials"] is True


def test_change_credentials_rotates_account(client: TestClient, fresh_app) -> None:
    _login(client, "admin", "1234")
    resp = client.post(
        "/api/auth/change-credentials", json={"username": "onyx", "password": "hunter2"}
    )
    assert resp.status_code == 200
    assert resp.json()["must_change_credentials"] is False
    assert resp.json()["username"] == "onyx"

    # The old account is gone; the new one works on a fresh session.
    fresh = fresh_app()
    assert _login(fresh, "admin", "1234").status_code == 401
    assert _login(fresh, "onyx", "hunter2").status_code == 200


def test_logout_clears_session(client: TestClient) -> None:
    _login(client, "admin", "1234")
    resp = client.post("/api/auth/logout")
    assert resp.status_code == 200
    set_cookie = resp.headers.get("set-cookie", "")
    assert "onyx_session=" in set_cookie and "max-age=0" in set_cookie.lower()

    status = client.get("/api/auth/status").json()
    assert status["authenticated"] is False


def test_unauthenticated_api_returns_401_json(client: TestClient) -> None:
    resp = client.get("/api/library")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "authentication required"}

    resp = client.get("/api/config")
    assert resp.status_code == 401


def test_authenticated_api_passes(client: TestClient) -> None:
    _login(client, "admin", "1234")
    assert client.get("/api/config").status_code == 200
    assert client.get("/api/library").status_code == 200


def test_unauthenticated_websocket_is_rejected(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/queue"):
            pass


def test_authenticated_websocket_connects(client: TestClient) -> None:
    _login(client, "admin", "1234")
    with client.websocket_connect("/ws/queue") as socket:
        payload = socket.receive_json()
        assert "torrents" in payload


def test_root_and_login_page_stay_open_without_session(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/login").status_code == 200
    assert client.get("/favicon.ico").status_code == 200


def test_startup_warns_while_default_account_stands(
    web_app, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level("WARNING"):
        with patch("arr.pipeline.ensure_daemon", return_value=None):
            with TestClient(web_app) as c:
                assert c.get("/api/auth/status").json()["must_change_credentials"] is True
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("admin / 1234" in w for w in warnings)
    # The warning names the defaults, never a password hash.
    assert not any("pbkdf2_sha256$" in w for w in warnings)


def test_default_login_warns(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        resp = _login(client, "admin", "1234")
    assert resp.status_code == 200
    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert any("default" in w.lower() for w in warnings)
    assert not any("pbkdf2_sha256$" in w for w in warnings)


def test_full_login_flow_end_to_end(client: TestClient) -> None:
    """5.1: status -> default login -> forced change -> access -> logout ->
    401 -> login with the new credentials, through the real HTTP stack."""
    # 1. Unauthenticated status.
    status = client.get("/api/auth/status").json()
    assert status["authenticated"] is False

    # 2. Login with the seeded defaults.
    login = _login(client, "admin", "1234")
    assert login.status_code == 200
    assert login.json()["must_change_credentials"] is True

    # 3. Forced change of credentials.
    change = client.post(
        "/api/auth/change-credentials", json={"username": "onyx", "password": "hunter2"}
    )
    assert change.status_code == 200
    assert change.json()["must_change_credentials"] is False

    # 4. Authenticated access while the session is live.
    assert client.get("/api/config").status_code == 200

    # 5. Logout ends the session.
    assert client.post("/api/auth/logout").status_code == 200

    # 6. The old session is gone.
    assert client.get("/api/config").status_code == 401

    # 7. The new credentials log in; the flag stays cleared.
    relogin = _login(client, "onyx", "hunter2")
    assert relogin.status_code == 200
    assert relogin.json()["username"] == "onyx"
    assert relogin.json()["must_change_credentials"] is False
    assert client.get("/api/config").status_code == 200
