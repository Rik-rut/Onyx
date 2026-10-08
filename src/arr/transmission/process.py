from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from arr.transmission.errors import (
    AuthError,
    DependencyUnavailable,
    PortInUseError,
    RpcError,
    StaleLockError,
    TransmissionError,
)


def _which(name: str) -> str | None:
    return shutil.which(name)


def _program_files_candidates() -> list[Path]:
    cands: list[Path] = []
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(env)
        if base:
            cands.append(Path(base) / "Transmission")
    return cands


def find_binary(name: str, override: str = "") -> str | None:
    if override:
        p = Path(override)
        if p.exists():
            return str(p)
    found = _which(name)
    if found:
        return found
    if sys.platform == "win32":
        exe = name if name.endswith(".exe") else f"{name}.exe"
        for base in _program_files_candidates():
            cand = base / exe
            if cand.exists():
                return str(cand)
    return None


def find_remote(override: str = "") -> str:
    path = find_binary("transmission-remote", override)
    if path is None:
        raise DependencyUnavailable("transmission-remote not found")
    return path


def find_daemon() -> str | None:
    return find_binary("transmission-daemon")


def port_in_use(port: int, *, timeout: float = 0.5) -> bool:
    """True when something is already listening on 127.0.0.1:port."""
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex(("127.0.0.1", port)) == 0


def lock_file_paths() -> list[Path]:
    """Known transmission-daemon lock file locations."""
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        base = Path(appdata) / "Transmission" if appdata else home / "Transmission"
    else:
        base = home / ".config" / "transmission"
    return [base / "transmission-daemon" / "lock", base / "lock"]


def find_stale_lock() -> Path | None:
    """Return an existing transmission-daemon lock file, if any."""
    for lock in lock_file_paths():
        if lock.exists():
            return lock
    return None


class Daemon:
    def __init__(self, download_dir: str, port: int = 9091):
        self.download_dir = download_dir
        self.port = port
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        binary = find_daemon()
        if binary is None:
            raise DependencyUnavailable("transmission-daemon not found")
        if self._proc is not None and self._proc.poll() is None:
            return
        if port_in_use(self.port):
            raise PortInUseError(self.port)
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        try:
            self._proc = subprocess.Popen(
                [binary, "-f", "--port", str(self.port), "-w", self.download_dir],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as e:
            raise TransmissionError(f"Failed to start transmission-daemon: {e}") from e
        time.sleep(1.0)
        if self._proc.poll() is not None:
            # daemon exited immediately; a stale lock is the common cause
            lock = find_stale_lock()
            if lock is not None:
                raise StaleLockError(
                    f"transmission-daemon exited at startup; stale lock at {lock}"
                )
            raise TransmissionError("transmission-daemon exited immediately at startup")

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None

    @property
    def process(self) -> subprocess.Popen | None:
        return self._proc


class RpcClient:
    def __init__(self, host: str, port: int, user: str = "", password: str = ""):
        import httpx

        self._httpx = httpx
        self._base = f"http://{host}:{port}/transmission/rpc"
        self._auth = (user, password) if user else None
        self._session_id: str | None = None

    async def _request(self, method: str, arguments: dict | None = None) -> dict:
        import httpx

        headers = {}
        if self._session_id:
            headers["X-Transmission-Session-Id"] = self._session_id
        payload = {"method": method, "arguments": arguments or {}}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    self._base,
                    json=payload,
                    auth=self._auth,  # type: ignore[arg-type]
                    headers=headers,
                )
                if resp.status_code == 409:
                    self._session_id = resp.headers.get("X-Transmission-Session-Id")
                    resp = await client.post(
                        self._base,
                        json=payload,
                        auth=self._auth,  # type: ignore[arg-type]
                        headers={"X-Transmission-Session-Id": self._session_id or ""},
                    )
        except httpx.HTTPError as e:
            # A refused/unreachable daemon is a dependency problem (exit 4), not
            # a generic runtime error.
            raise DependencyUnavailable(
                f"transmission-daemon RPC unreachable at {self._base}: {e}"
            ) from e
        if resp.status_code == 401:
            raise AuthError()
        if resp.status_code != 200:
            raise RpcError(f"RPC HTTP {resp.status_code} for {method}")
        data = resp.json()
        if data.get("result") != "success":
            raise RpcError(f"RPC error for {method}: {data.get('result')}")
        return data.get("arguments", {})

    async def add_magnet(self, magnet: str, download_dir: str, paused: bool = False) -> dict:
        args: dict = {"filename": magnet, "download-dir": download_dir}
        if paused:
            args["paused"] = True
        return await self._request("torrent-add", args)

    async def list_torrents(self) -> list[dict]:
        fields = [
            "id", "hashString", "name", "status", "percentDone", "rateDownload",
            "rateUpload", "uploadRatio", "eta", "errorString", "downloadDir",
            "secondsSeeding", "doneDate",
        ]
        args = await self._request("torrent-get", {"fields": fields})
        return args.get("torrents", [])

    async def get(self, torrent_id: int | str) -> dict | None:
        torrents = await self.list_torrents()
        for t in torrents:
            if str(t.get("id")) == str(torrent_id) or t.get("hashString", "").startswith(
                str(torrent_id)
            ):
                return t
        return None

    async def remove(self, torrent_id: int | str, delete_data: bool = False) -> dict:
        t = await self.get(torrent_id)
        if t is None:
            raise RpcError(f"Torrent {torrent_id} not found")
        return await self._request(
            "torrent-remove", {"ids": [t["id"]], "delete-local-data": delete_data}
        )

    async def start(self, torrent_id: int | str) -> dict:
        t = await self.get(torrent_id)
        if t is None:
            raise RpcError(f"Torrent {torrent_id} not found")
        return await self._request("torrent-start", {"ids": [t["id"]]})

    async def stop(self, torrent_id: int | str) -> dict:
        t = await self.get(torrent_id)
        if t is None:
            raise RpcError(f"Torrent {torrent_id} not found")
        return await self._request("torrent-stop", {"ids": [t["id"]]})


# Transmission RPC torrent status codes.
STOPPED = 0
DOWNLOAD = 4
SEED = 6


def is_active_torrent(t: dict) -> bool:
    """True when a torrent is actively downloading/seeding (occupies a slot)."""
    if int(t.get("status") or 0) == STOPPED:
        return False
    return float(t.get("percentDone") or 0) < 1.0


def active_count(torrents: list[dict]) -> int:
    return sum(1 for t in torrents if is_active_torrent(t))


def is_complete_torrent(t: dict) -> bool:
    """True when a torrent has finished downloading (seeding or 100%)."""
    return int(t.get("status") or 0) == SEED or float(t.get("percentDone") or 0) >= 1.0


def plan_slots(active: int, limit: int, count: int) -> list[bool]:
    """Paused flags for `count` new torrents given `active` currently in flight.

    Returns True where the torrent should be added stopped (queued) because no
    slot is free. Deterministic and side-effect free so it can be unit tested.
    """
    limit = max(1, limit)
    return [active + i >= limit for i in range(max(0, count))]


class ConcurrencyGate:
    def __init__(self, max_concurrent: int):
        self._sem = asyncio.Semaphore(max(1, max_concurrent))

    async def acquire(self) -> None:
        await self._sem.acquire()

    def release(self) -> None:
        self._sem.release()

    @property
    def limit(self) -> int:
        return self._sem._value if hasattr(self._sem, "_value") else 0
