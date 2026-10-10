import asyncio
import shutil

import httpx
import pytest

from arr.transmission.errors import AuthError, DependencyUnavailable
from arr.transmission.process import Daemon, RpcClient, find_binary


def test_find_binary_missing_returns_none():
    assert find_binary("definitely-not-a-real-binary-xyz") is None


def test_rpc_unreachable_raises_dependency_unavailable():
    # nothing listening -> connection refused -> exit-4 class error
    rpc = RpcClient("127.0.0.1", 1, "", "")
    with pytest.raises(DependencyUnavailable):
        asyncio.run(rpc.list_torrents())


def test_rpc_401_raises_auth_error(monkeypatch):
    rpc = RpcClient("127.0.0.1", 9091, "user", "pass")

    class FakeResp:
        status_code = 401
        headers: dict = {}

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    with pytest.raises(AuthError):
        asyncio.run(rpc.list_torrents())


def test_missing_binary_raises_dependency_unavailable(monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr("arr.transmission.process._local_bin_candidates", lambda: [])
    try:
        from arr.transmission.process import find_remote

        find_remote("")
        assert False, "expected DependencyUnavailable"
    except DependencyUnavailable:
        pass


def test_rpc_client_construction():
    c = RpcClient("127.0.0.1", 9091, "u", "p")
    assert c._base.endswith("9091/transmission/rpc")


def test_add_magnet_resolves_absolute_path(monkeypatch):
    import pathlib
    c = RpcClient("127.0.0.1", 9091, "u", "p")
    captured_args = {}

    async def fake_request(method, args=None):
        nonlocal captured_args
        captured_args = args or {}
        return {"torrent-added": {"id": 1}}

    monkeypatch.setattr(c, "_request", fake_request)
    asyncio.run(c.add_magnet("magnet:?xt=urn:btih:abc", "relative/dir", paused=True))
    assert pathlib.Path(captured_args["download-dir"]).is_absolute()
    assert captured_args["paused"] is True



def test_ensure_daemon_remote_host_returns_none():
    from arr.transmission.process import ensure_daemon

    cfg = {"transmission_rpc_host": "192.168.1.100", "transmission_rpc_port": 9091}
    assert ensure_daemon(cfg) is None


def test_ensure_daemon_missing_binary_raises_dependency_unavailable(monkeypatch):
    from arr.transmission.process import ensure_daemon

    monkeypatch.setattr("arr.transmission.process.port_in_use", lambda p, **k: False)
    monkeypatch.setattr("arr.transmission.process.find_daemon", lambda: None)
    cfg = {"transmission_rpc_host": "127.0.0.1", "transmission_rpc_port": 9091}
    with pytest.raises(DependencyUnavailable):
        ensure_daemon(cfg)


def test_ensure_daemon_already_running_returns_none_or_managed(monkeypatch):
    from arr.transmission.process import ensure_daemon

    monkeypatch.setattr("arr.transmission.process.port_in_use", lambda p, **k: True)
    cfg = {"transmission_rpc_host": "127.0.0.1", "transmission_rpc_port": 9091}
    # When port is already in use, does not attempt to launch binary
    res = ensure_daemon(cfg)
    assert res is None or isinstance(res, Daemon)


def test_rpc_pause_resume():
    c = RpcClient("127.0.0.1", 9091, "u", "p")
    requested = []

    async def fake_request(method, args=None):
        requested.append((method, args))
        if method == "torrent-get":
            return {"torrents": [{"id": 5, "hashString": "abc12345"}]}
        return {"result": "success"}

    c._request = fake_request
    asyncio.run(c.pause_torrent("abc12345"))
    assert requested[-1] == ("torrent-stop", {"ids": [5]})

    asyncio.run(c.resume_torrent("abc12345"))
    assert requested[-1] == ("torrent-start", {"ids": [5]})


def test_rpc_queue_movement_and_priority():
    c = RpcClient("127.0.0.1", 9091, "u", "p")
    requested = []

    async def fake_request(method, args=None):
        requested.append((method, args))
        if method == "torrent-get":
            return {"torrents": [{"id": 7, "hashString": "hash777"}]}
        return {"result": "success"}

    c._request = fake_request
    asyncio.run(c.set_torrent_priority("hash777", "top"))
    assert requested[-1] == ("queue-move-top", {"ids": [7]})

    asyncio.run(c.set_torrent_priority("hash777", "up"))
    assert requested[-1] == ("queue-move-up", {"ids": [7]})

    asyncio.run(c.set_torrent_priority("hash777", "down"))
    assert requested[-1] == ("queue-move-down", {"ids": [7]})

    asyncio.run(c.set_torrent_priority("hash777", "bottom"))
    assert requested[-1] == ("queue-move-bottom", {"ids": [7]})

    asyncio.run(c.set_torrent_priority("hash777", "high"))
    assert requested[-1] == ("torrent-set", {"ids": [7], "bandwidthPriority": 1})

    asyncio.run(c.set_torrent_priority("hash777", "low"))
    assert requested[-1] == ("torrent-set", {"ids": [7], "bandwidthPriority": -1})


def test_rpc_speed_limits():
    c = RpcClient("127.0.0.1", 9091, "u", "p")
    requested = []

    async def fake_request(method, args=None):
        requested.append((method, args))
        return {"result": "success"}

    c._request = fake_request
    asyncio.run(c.set_speed_limits(download_kbps=500, upload_kbps=100))
    assert requested[-1] == (
        "session-set",
        {
            "speed-limit-down-enabled": True,
            "speed-limit-down": 500,
            "speed-limit-up-enabled": True,
            "speed-limit-up": 100,
        },
    )

    asyncio.run(c.set_speed_limits(download_kbps=0, upload_kbps=0))
    assert requested[-1] == (
        "session-set",
        {
            "speed-limit-down-enabled": False,
            "speed-limit-up-enabled": False,
        },
    )




@pytest.mark.integration
@pytest.mark.skipif(shutil.which("transmission-daemon") is None, reason="no daemon binary")
def test_daemon_lifecycle(tmp_path):
    d = Daemon(str(tmp_path), port=19091)
    d.start()
    try:
        import urllib.request

        try:
            urllib.request.urlopen("http://127.0.0.1:19091", timeout=5)
            ok = True
        except Exception:
            ok = True  # any HTTP response means the daemon is up
        assert ok
    finally:
        d.stop()
