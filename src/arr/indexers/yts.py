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
        resp = await self.http.get(url, key="yts", ttl_seconds=3600, params={"query_term": q.text})
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise SchemaMismatchError(self.name, url, f"invalid JSON: {e}") from e
        try:
            movies = data["data"]["movies"] or []
        except (KeyError, TypeError) as e:
            raise SchemaMismatchError(self.name, url, "missing data.movies") from e
        out: list[Release] = []
        for m in movies:
            try:
                for t in m.get("torrents", []) or []:
                    h = t.get("hash")
                    if not h:
                        continue
                    out.append(
                        Release(
                            indexer=self.name,
                            title=f"{m.get('title', '')} {m.get('year', '')} {t.get('quality', '')} {t.get('type', '')}".strip(),
                            infohash=str(h).lower(),
                            magnet=f"magnet:?xt=urn:btih:{h}",
                            media_type=MediaType.MOVIE,
                            seeds=int(t.get("seeds", 0) or 0),
                            peers=int(t.get("peers", 0) or 0),
                            size_bytes=int(t.get("size_bytes", 0) or 0),
                            quality=t.get("quality"),
                            year=m.get("year"),
                            tmdb_id=m.get("id"),
                        )
                    )
            except (KeyError, TypeError, ValueError) as e:
                raise SchemaMismatchError(self.name, url, str(e)) from e
        return out
