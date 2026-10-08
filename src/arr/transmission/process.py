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
    RpcError,
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


class Daemon:
    def __init__(self, download_dir: str, port: int = 9091):
        self.download_dir = download_dir
        self.port = port
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        binary = find_daemon()
        if binary is None:
            raise DependencyUnavailable("transmission-daemon not found")
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
            raise RpcError(f"RPC request failed: {e}") from e
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
