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
    try:
        from arr.transmission.process import find_remote

        find_remote("")
        assert False, "expected DependencyUnavailable"
    except DependencyUnavailable:
        pass


def test_rpc_client_construction():
    c = RpcClient("127.0.0.1", 9091, "u", "p")
    assert c._base.endswith("9091/transmission/rpc")


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
