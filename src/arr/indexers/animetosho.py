"""Anime Tosho (animetosho.net) indexer adapter.

Scrapes the server-rendered HTML search page (``GET /search?q=<title>``) and
maps each result row to a :class:`Release` (design D1). Query handling
mirrors :class:`NyaaAdapter`: non-anime TV queries carry ``Sxx``/``SxxEyy``
tokens; anime queries rely on the ranker's episode-number scoping (design
D3). Supports TV + MOVIE, since Anime Tosho files anime theatrical
releases together with episodes.
"""

from __future__ import annotations

import base64

from arr.core.models import MediaType, Query, Release
from arr.indexers.animetosho_parser import parse_rows
from arr.indexers.base import HttpClient


class AnimetoshoAdapter:
    name = "animetosho"

    def __init__(self, base_url: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def supports(self, media_type: MediaType) -> bool:
        return media_type in (MediaType.TV, MediaType.MOVIE)

    async def search(self, q: Query) -> list[Release]:
        url = f"{self.base_url}/search"
        # Season/episode scoping (design D3): Sxx/Eyy tokens narrow the
        # indexer's own results. Anime releases number episodes across the
        # whole series, so the tokens are omitted there.
        text = (q.text or "").strip()
        if q.media_type == MediaType.TV and q.season is not None and not q.anime:
            token = f"S{q.season:02d}"
            if q.episode is not None:
                token += f"E{q.episode:02d}"
            text = f"{text} {token}".strip()
        resp = await self.http.get(
            url, key="animetosho", ttl_seconds=1800, params={"q": text}
        )
        if resp.status_code != 200:
            return []
        rows = parse_rows(resp.text)
        return [
            Release(
                indexer=self.name,
                title=row["title"],
                infohash=_hash_from_magnet(row["magnet"]),
                magnet=row["magnet"],
                media_type=q.media_type or MediaType.TV,
                seeds=row["seeders"],
                peers=row["leechers"],
                size_bytes=row["size_bytes"],
            )
            for row in rows
        ]


def _hash_from_magnet(magnet: str) -> str:
    """Extract the infohash from a magnet URI, normalized to 40-hex.

    Anime Tosho mixes 40-hex and 32-base32 infohashes in its magnets. The
    hash is read up to the next ``&`` delimiter (not a fixed length), and a
    base32 hash is converted to hex so queue matching against Transmission
    (which keys torrents by hex hashString) works.
    """
    marker = "btih:"
    start = magnet.find(marker)
    if start < 0:
        return ""
    end = magnet.find("&", start + len(marker))
    raw = magnet[start + len(marker) : end if end > 0 else len(magnet)]
    if len(raw) == 40:
        return raw.lower()
    try:
        return base64.b32decode(raw.upper()).hex()
    except ValueError:
        return raw.lower()
