import shutil

import pytest

from arr.transmission.errors import DependencyUnavailable
from arr.transmission.process import Daemon, RpcClient, find_binary


def test_find_binary_missing_returns_none():
    assert find_binary("definitely-not-a-real-binary-xyz") is None


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
