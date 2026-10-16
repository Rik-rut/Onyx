"""Movie discovery from YTS's public catalogue (no API key needed).

YTS also serves the movie downloads, so every title Discover shows can be downloaded
through the existing YTS indexer. Pages are cached on disk like the other clients.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

LIST_PATH = "/api/v2/list_movies.json"


class YtsError(Exception):
    pass


class YtsCatalog:
    def __init__(self, cfg: Any, cache_dir: Path | None = None) -> None:
        self.cfg = cfg
        self.base = str(cfg.get("yts_base_url", "https://yts.lt")).rstrip("/")
        self.cache_dir = cache_dir or Path(".cache") / "arr" / "yts"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def browse(
        self, *, genre: str | None, page: int, limit: int = 20
    ) -> tuple[list[dict[str, Any]], int]:
        """One page of movies, most downloaded first. Returns (items, total matches)."""
        params: dict[str, Any] = {
            "page": max(1, page),
            "limit": limit,
            "sort_by": "download_count",
            "order_by": "desc",
        }
        if genre:
            params["genre"] = genre
        data = self._get(params)
        movies = data.get("movies") or []
        total = int(data.get("movie_count") or 0)
        return [self._item(m) for m in movies if isinstance(m, dict)], total

    def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        cache_file = self._cache_path(params)
        ttl = float(self.cfg.get("cache_ttl_hours", 24)) * 3600
        if cache_file.exists() and time.time() - cache_file.stat().st_mtime <= ttl:
            return self._read(cache_file)
        try:
            # yts.lt redirects to the live mirror, so redirects must be followed.
            with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                resp = client.get(f"{self.base}{LIST_PATH}", params=params)
            if resp.status_code != 200:
                raise YtsError(f"YTS HTTP {resp.status_code}")
            payload = resp.json()
        except (httpx.HTTPError, ValueError, YtsError) as e:
            if cache_file.exists():  # a stale page is better than no page
                return self._read(cache_file)
            raise YtsError(f"YTS unreachable: {e}") from e
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise YtsError("YTS returned no data object")
        try:
            cache_file.write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
        return data

    def _cache_path(self, params: dict[str, Any]) -> Path:
        key = json.dumps({"base": self.base, **params}, sort_keys=True)
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()[:24]}.json"

    @staticmethod
    def _read(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _item(movie: dict[str, Any]) -> dict[str, Any]:
        imdb = str(movie.get("imdb_code") or "")
        return {
            "id": imdb or str(movie.get("id") or ""),
            "imdb_id": imdb or None,
            "title": str(movie.get("title") or ""),
            "year": movie.get("year"),
            "rating": movie.get("rating"),
            "poster": str(movie.get("medium_cover_image") or movie.get("large_cover_image") or ""),
            "genres": [str(g) for g in (movie.get("genres") or [])],
            "overview": str(movie.get("summary") or ""),
            "media_type": "movie",
            "source": "YTS",
        }
