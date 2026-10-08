from __future__ import annotations

import json

from arr.core.models import MediaType, Query, Release
from arr.indexers.base import HttpClient, SchemaMismatchError


class EztvAdapter:
    name = "eztv"

    def __init__(self, base_url: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def supports(self, media_type: MediaType) -> bool:
        return media_type == MediaType.TV

    async def search(self, q: Query) -> list[Release]:
        url = f"{self.base_url}/api/get-torrents"
        params: dict[str, object] = {"limit": q.limit}
        if q.imdb_id:
            params["imdb_id"] = q.imdb_id.lstrip("tt")
        else:
            params["query"] = q.text
        resp = await self.http.get(url, key="eztv", ttl_seconds=3600, params=params)
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as e:
            raise SchemaMismatchError(self.name, url, f"invalid JSON: {e}") from e
        try:
            torrents = data["torrents"] or []
        except (KeyError, TypeError) as e:
            raise SchemaMismatchError(self.name, url, "missing torrents") from e
        out: list[Release] = []
        for t in torrents:
            try:
                magnet = t.get("magnet_url") or t.get("magnet") or ""
                if not magnet:
                    continue
                size = t.get("size_bytes") or 0
                out.append(
                    Release(
                        indexer=self.name,
                        title=t.get("title", ""),
                        infohash=_hash_from_magnet(magnet),
                        magnet=magnet,
                        media_type=MediaType.TV,
                        seeds=int(t.get("seeds", 0) or 0),
                        peers=int(t.get("peers", 0) or 0),
                        size_bytes=int(size) if str(size).isdigit() else 0,
                        season=_to_int(t.get("season")),
                        episode=_to_int(t.get("episode")),
                        imdb_id=t.get("imdb_id"),
                    )
                )
            except (KeyError, TypeError, ValueError) as e:
                raise SchemaMismatchError(self.name, url, str(e)) from e
        return out


def _to_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _hash_from_magnet(magnet: str) -> str:
    marker = "btih:"
    idx = magnet.lower().find(marker)
    if idx >= 0:
        return magnet[idx + len(marker) :].split("&")[0].lower()
    return magnet[:40].lower()
