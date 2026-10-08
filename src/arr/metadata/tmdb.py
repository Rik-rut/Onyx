from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

from arr.core.models import Episode, Season, Series


class TmdbError(Exception):
    pass


class TmdbClient:
    def __init__(self, cfg, cache_dir: Path | None = None):
        self.cfg = cfg
        self.base = str(cfg.get("tmdb_base_url", "https://api.themoviedb.org/3")).rstrip("/")
        self.key = str(cfg.get("tmdb_api_key", ""))
        self.cache_dir = cache_dir or Path.home() / ".cache" / "arr" / "tmdb"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, path: str, params: dict) -> Path:
        import hashlib

        h = hashlib.sha256((path + json.dumps(params, sort_keys=True)).encode()).hexdigest()[:24]
        return self.cache_dir / f"{h}.json"

    def _ttl(self, path: str, series: Series | None = None) -> float:
        general = float(self.cfg.get("cache_ttl_hours", 24)) * 3600
        if series is not None and series.status == "Returning Series" and "/season/" in path:
            return float(self.cfg.get("episode_cache_ttl_hours", 6)) * 3600
        return general

    def _get(self, path: str, params: dict | None = None, *, series: Series | None = None, force_cache_ok: bool = True):
        params = dict(params or {})
        params["api_key"] = self.key
        ttl = self._ttl(path, series)
        cp = self._cache_path(path, {k: v for k, v in params.items() if k != "api_key"})
        if cp.exists() and (time.time() - cp.stat().st_mtime) <= ttl:
            return json.loads(cp.read_text(encoding="utf-8"))
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{self.base}{path}", params=params)
            if resp.status_code != 200:
                raise TmdbError(f"TMDB HTTP {resp.status_code}")
            data = resp.json()
            try:
                cp.write_text(json.dumps(data), encoding="utf-8")
            except OSError:
                pass
            return data
        except (httpx.HTTPError, TmdbError) as e:
            if force_cache_ok and cp.exists():
                try:
                    return json.loads(cp.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
            raise TmdbError(str(e)) from e

    def search_movie(self, query: str) -> dict | None:
        data = self._get("/search/movie", {"query": query})
        results = data.get("results") or []
        return results[0] if results else None

    def search_tv(self, query: str) -> dict | None:
        data = self._get("/search/tv", {"query": query})
        results = data.get("results") or []
        return results[0] if results else None

    def tv_details(self, tmdb_id: int) -> Series:
        data = self._get(f"/tv/{tmdb_id}")
        return Series(
            tmdb_id=data["id"],
            title=data.get("name", ""),
            year=_year(data.get("first_air_date")),
            imdb_id=None,
            status=data.get("status", ""),
            seasons=[],
        )

    def tv_external_ids(self, tmdb_id: int) -> dict:
        return self._get(f"/tv/{tmdb_id}/external_ids")

    def movie_details(self, tmdb_id: int) -> dict:
        return self._get(f"/movie/{tmdb_id}")

    def season(self, tmdb_id: int, season_number: int, series: Series | None = None) -> Season:
        data = self._get(f"/tv/{tmdb_id}/season/{season_number}", series=series)
        eps = []
        for e in data.get("episodes", []) or []:
            eps.append(
                Episode(
                    tmdb_id=tmdb_id,
                    season_number=season_number,
                    episode_number=int(e.get("episode_number", 0)),
                    name=e.get("name", ""),
                    air_date=e.get("air_date"),
                )
            )
        return Season(season_number=season_number, episodes=eps)

    def full_series(self, tmdb_id: int) -> Series:
        series = self.tv_details(tmdb_id)
        try:
            ext = self.tv_external_ids(tmdb_id)
            series.imdb_id = ext.get("imdb_id")
            series.tvdb_id = ext.get("tvdb_id")
        except TmdbError:
            pass
        raw = self._get(f"/tv/{tmdb_id}")
        for s in raw.get("seasons", []) or []:
            n = s.get("season_number")
            if n is None or n == 0:
                continue
            try:
                series.seasons.append(self.season(tmdb_id, n, series=series))
            except TmdbError as e:
                warn(f"TMDB season {n} fetch failed: {e}")
        return series


def _year(date: str | None) -> int | None:
    if date and len(date) >= 4 and date[:4].isdigit():
        return int(date[:4])
    return None


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def degrade(query: str) -> None:
    print(f"warning: TMDB unreachable; falling back to free-text search for {query!r}", file=sys.stderr)
