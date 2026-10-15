"""Test-suite guards.

Unit tests must never depend on external network access: metadata scrapers,
subtitles, and indexers are all exercised through injected fakes or respx.
Any test that tries to reach a non-loopback host fails loudly instead of
silently succeeding on a machine that happens to be online.

Loopback connections stay allowed because Windows asyncio event loops (and the
Starlette TestClient) implement their internal self-pipe over 127.0.0.1.
"""

from __future__ import annotations

import socket

import pytest

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "0.0.0.0", ""}
# A Transmission daemon listening locally must never be what makes a test pass.
_BLOCKED_PORTS = {9091}


class NetworkAccessAttempted(RuntimeError):
    """Raised when a unit test tries to reach the public network."""


def _port_of(address) -> int | None:
    if isinstance(address, (tuple, list)) and len(address) >= 2:
        try:
            return int(address[1])
        except (TypeError, ValueError):
            return None
    return None


def _is_loopback(address) -> bool:
    host = ""
    if isinstance(address, (tuple, list)) and address:
        host = address[0]
    elif isinstance(address, (str, bytes)):
        host = address.decode() if isinstance(address, bytes) else address
    return str(host) in _LOOPBACK_HOSTS


@pytest.fixture(autouse=True)
def _no_external_network(monkeypatch):
    """Block outbound connections to anything that is not loopback."""
    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def guarded_connect(self, address, *args, **kwargs):
        if not _is_loopback(address) or _port_of(address) in _BLOCKED_PORTS:
            raise NetworkAccessAttempted(
                f"unit tests must stay offline (tried to connect to {address!r})"
            )
        return real_connect(self, address, *args, **kwargs)

    def guarded_connect_ex(self, address, *args, **kwargs):
        if not _is_loopback(address) or _port_of(address) in _BLOCKED_PORTS:
            raise NetworkAccessAttempted(
                f"unit tests must stay offline (tried to connect to {address!r})"
            )
        return real_connect_ex(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect, raising=True)
    monkeypatch.setattr(socket.socket, "connect_ex", guarded_connect_ex, raising=True)
    yield
