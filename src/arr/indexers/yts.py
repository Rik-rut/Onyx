from __future__ import annotations

import json

from arr.core.models import MediaType, Query, Release
from arr.indexers.base import HttpClient, SchemaMismatchError


class YtsAdapter:
    name = "yts"

    def __init__(self, base_url: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def supports(self, media_type: MediaType) -> bool:
        return media_type == MediaType.MOVIE

    async def search(self, q: Query) -> list[Release]:
        url = f"{self.base_url}/api/v2/list_movies.json"
        movies: list[dict] = []

        # 1. Search by imdb_id if available for precise matching
        if q.imdb_id:
            try:
                resp = await self.http.get(
                    url, key="yts", ttl_seconds=3600, params={"query_term": q.imdb_id}
                )
                data = resp.json()
                if isinstance(data, dict) and isinstance(data.get("data"), dict):
                    movies = data["data"].get("movies") or []
            except Exception:
                movies = []

        # 2. Fall back to title / query_term if no movies found yet
        if not movies:
            term = (q.text or q.title or "").strip()
            resp = await self.http.get(
                url, key="yts", ttl_seconds=3600, params={"query_term": term}
            )
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError) as e:
                raise SchemaMismatchError(self.name, url, f"invalid JSON: {e}") from e
            if (
                not isinstance(data, dict)
                or "data" not in data
                or not isinstance(data["data"], dict)
            ):
                raise SchemaMismatchError(self.name, url, "missing data object")
            movies = data["data"].get("movies") or []

        # 3. Filter candidate movies if year or imdb_id was specified
        filtered_movies = []
        for m in movies:
            if q.imdb_id and m.get("imdb_code") and m.get("imdb_code") == q.imdb_id:
                filtered_movies.append(m)
                continue
            m_year = m.get("year")
            if q.year is not None and m_year is not None and abs(int(m_year) - q.year) > 1:
                continue
            filtered_movies.append(m)

        target_movies = filtered_movies if filtered_movies else movies
        out: list[Release] = []
        for m in target_movies:
            try:
                for t in m.get("torrents", []) or []:
                    h = t.get("hash")
                    if not h:
                        continue
                    title = (
                        f"{m.get('title', '')} {m.get('year', '')} "
                        f"{t.get('quality', '')} {t.get('type', '')}"
                    ).strip()
                    out.append(
                        Release(
                            indexer=self.name,
                            title=title,
                            infohash=str(h).lower(),
                            magnet=f"magnet:?xt=urn:btih:{h}",
                            media_type=MediaType.MOVIE,
                            seeds=int(t.get("seeds", 0) or 0),
                            peers=int(t.get("peers", 0) or 0),
                            size_bytes=int(t.get("size_bytes", 0) or 0),
                            quality=t.get("quality"),
                            year=m.get("year"),
                            imdb_id=m.get("imdb_code"),
                            tmdb_id=m.get("id"),
                        )
                    )
            except (KeyError, TypeError, ValueError) as e:
                raise SchemaMismatchError(self.name, url, str(e)) from e
        return out
