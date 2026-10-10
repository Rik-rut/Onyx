from __future__ import annotations

import asyncio
import hashlib
import json
import random
import time
from pathlib import Path

import httpx


class IndexerError(Exception):
    pass


class SchemaMismatchError(IndexerError):
    def __init__(self, adapter: str, url: str, detail: str = ""):
        super().__init__(f"[{adapter}] unexpected response schema from {url}: {detail}")
        self.adapter = adapter
        self.url = url


class HttpClient:
    def __init__(self, cfg, cache_dir: Path | None = None):
        self.cfg = cfg
        self._last: dict[str, float] = {}
        self._cache_dir = cache_dir or Path(".cache") / "arr" / "http"
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _interval(self, key: str) -> float:
        intervals = self.cfg.get("request_interval_seconds") or {}
        try:
            return float(intervals.get(key, 1.0))
        except (AttributeError, TypeError, ValueError):
            return 1.0

    async def _throttle(self, key: str) -> None:
        interval = self._interval(key)
        now = time.monotonic()
        last = self._last.get(key, 0.0)
        wait = interval - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last[key] = time.monotonic()

    def _cache_path(self, url: str) -> Path:
        h = hashlib.sha256(url.encode()).hexdigest()[:24]
        return self._cache_dir / f"{h}.json"

    def cache_get(self, url: str, ttl_seconds: float) -> bytes | None:
        p = self._cache_path(url)
        if not p.exists():
            return None
        age = time.time() - p.stat().st_mtime
        if age > ttl_seconds:
            return None
        return p.read_bytes()

    def cache_put(self, url: str, data: bytes) -> None:
        try:
            self._cache_path(url).write_bytes(data)
        except OSError:
            pass

    async def get(
        self,
        url: str,
        *,
        key: str = "default",
        ttl_seconds: float = 0,
        params: dict | None = None,
    ) -> httpx.Response:
        if ttl_seconds > 0:
            cached = self.cache_get(url + json.dumps(params or {}, sort_keys=True), ttl_seconds)
            if cached is not None:
                return httpx.Response(200, content=cached, request=httpx.Request("GET", url))
        await self._throttle(key)
        headers = {"User-Agent": str(self.cfg.get("user_agent", "arr/0.1"))}
        last_exc: Exception | None = None
        for attempt in range(4):
            try:
                async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
                    resp = await client.get(url, params=params, headers=headers)
                if resp.status_code in (429, 503):
                    delay = (2**attempt) + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)
                    continue
                if ttl_seconds > 0:
                    self.cache_put(url + json.dumps(params or {}, sort_keys=True), resp.content)
                return resp
            except httpx.HTTPError as e:
                last_exc = e
                await asyncio.sleep((2**attempt) + random.uniform(0, 0.5))
        raise IndexerError(f"GET {url} failed after retries: {last_exc}")


def tracker_list(cfg) -> list[str]:
    return []
