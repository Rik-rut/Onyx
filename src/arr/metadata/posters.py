"""Cover art for library entries, looked up on the free metadata sources.

Movies resolve through the IMDb suggestion API (by IMDb id, or by title and year) and
shows through TVMaze. Every answer is cached on disk, misses included, so the Library
never asks the network twice for the same title.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arr.db import normalize_title
from arr.log import get_logger
from arr.metadata.imdb import ImdbClient
from arr.metadata.matching import pick_match
from arr.metadata.tvmaze import TvmazeClient

logger = get_logger("posters")

HIT_TTL_SECONDS = 30 * 24 * 3600
MISS_TTL_SECONDS = 24 * 3600
_LOCK = threading.Lock()


class PosterResolver:
    def __init__(self, cfg: Any, cache_dir: Path | None = None) -> None:
        self.cfg = cfg
        if cache_dir is None:
            library = Path(str(cfg.get("library_root", "downloads"))).resolve()
            cache_dir = library.parent / ".cache" / "arr" / "posters"
        self.cache_path = Path(cache_dir) / "posters.json"

    def movie_poster(self, title: str, year: int | None, imdb_id: str | None) -> str:
        if imdb_id:
            return self._cached(
                f"movie:{imdb_id}",
                lambda: ImdbClient(self.cfg).poster_for_imdb_id(imdb_id),
            )
        return self._cached(
            f"movie:{normalize_title(title)}:{year or ''}",
            lambda: self._movie_by_title(title, year),
        )

    def show_poster(self, title: str, year: int | None, tmdb_id: int | None) -> str:
        if tmdb_id:
            return self._cached(f"tv:{int(tmdb_id)}", lambda: self._show_by_id(int(tmdb_id)))
        return self._cached(
            f"tv:{normalize_title(title)}:{year or ''}",
            lambda: self._show_by_title(title, year),
        )

    def _movie_by_title(self, title: str, year: int | None) -> str:
        candidates = ImdbClient(self.cfg).suggest_titles(title)
        match = pick_match(candidates, title, year, require_year=True)
        return str(match.get("poster") or "") if match else ""

    def _show_by_id(self, show_id: int) -> str:
        return str(TvmazeClient(self.cfg).tv_show_summary(show_id).get("poster") or "")

    def _show_by_title(self, title: str, year: int | None) -> str:
        match = pick_match(TvmazeClient(self.cfg).search_tv_shows(title), title, year)
        return str(match.get("poster") or "") if match else ""

    def _cached(self, key: str, lookup: Callable[[], str]) -> str:
        with _LOCK:
            entry = self._load().get(key)
        if isinstance(entry, dict):
            url = str(entry.get("url") or "")
            ttl = HIT_TTL_SECONDS if url else MISS_TTL_SECONDS
            if time.time() - float(entry.get("at") or 0) <= ttl:
                return url
        try:
            url = lookup() or ""
        except Exception as e:  # a blocked or offline source just means no cover art
            logger.debug(f"Cover lookup failed for {key}: {e}")
            url = ""
        with _LOCK:
            data = self._load()
            data[key] = {"url": url, "at": time.time()}
            self._store(data)
        return url

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _store(self, data: dict[str, Any]) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.cache_path)
        except OSError:
            pass
