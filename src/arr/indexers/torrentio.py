from __future__ import annotations

import logging
import time
from typing import Any

from arr.core.models import MediaType, Query, Release
from arr.indexers.base import HttpClient, SchemaMismatchError, tracker_list

logger = logging.getLogger(__name__)

# Module-level down-marker: after a connection failure, skip the network
# for 60 seconds without hitting the network at all.
_down_since: float = 0.0
_DOWN_TIMEOUT = 60  # seconds


def _is_down() -> bool:
    """Check if the sidecar is marked as down."""
    global _down_since
    if _down_since == 0:
        return False
    return (time.monotonic() - _down_since) < _DOWN_TIMEOUT


def _mark_down() -> None:
    """Mark the sidecar as down."""
    global _down_since
    _down_since = time.monotonic()


def _mark_up() -> None:
    """Clear the down marker."""
    global _down_since
    _down_since = 0


class TorrentioAdapter:
    """Torrentio sidecar indexer.

    Queries a locally self-hosted torrentio-scraper service that aggregates
    multiple public indexers behind a single search endpoint.
    """

    name = "torrentio"

    def __init__(
        self,
        base_url: str,
        http: HttpClient,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http

    def supports(self, media_type: MediaType) -> bool:
        return media_type in (MediaType.TV, MediaType.MOVIE)

    async def search(self, q: Query) -> list[Release]:
        """Search the Torrentio sidecar and return parsed Releases."""
        # Check down-marker: skip network if sidecar is down
        if _is_down():
            logger.debug("Torrentio sidecar is down, skipping network")
            return []

        media_type = q.media_type
        query = (q.text or q.title or "").strip()
        if not query:
            return []

        # Build query parameters
        params: dict[str, Any] = {"strict": "true"}
        if media_type == MediaType.MOVIE and q.imdb_id:
            params["title_id"] = q.imdb_id
        else:
            params["search_query"] = query

        url = f"{self.base_url}/search_for_torrents"

        try:
            resp = await self.http.get(
                url,
                key="torrentio",
                ttl_seconds=0,  # no caching for real-time search
                params=params,
            )
            data = resp.json()
        except Exception as exc:
            logger.warning("Torrentio connection failure: %s", exc)
            _mark_down()
            return []

        # Parse response
        try:
            torrents = data if isinstance(data, list) else data.get("torrents", [])
            if not isinstance(torrents, list):
                raise SchemaMismatchError(
                    self.name, url, f"expected list, got {type(data).__name__}"
                )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Torrentio response parse error: %s", exc)
            _mark_down()
            raise SchemaMismatchError(self.name, url, str(exc)) from exc

        # Clear down-marker on success
        _mark_up()

        trackers = tracker_list(self.http.cfg)
        return _map_torrents(torrents, trackers, media_type)


def _map_torrents(
    torrents: list[dict],
    trackers: list[str],
    media_type: MediaType,
) -> list[Release]:
    """Map Torrentio JSON payload to Release objects."""
    releases: list[Release] = []
    for t in torrents:
        try:
            torrent_hash = (
                t.get("infoHash") or t.get("info_hash") or t.get("hash", "")
            )
            if not torrent_hash:
                continue

            # Build magnet URI from hash + trackers
            magnet = _build_magnet(torrent_hash, trackers)

            size_bytes = 0
            size_raw = t.get("size") or t.get("size_bytes") or 0
            try:
                size_bytes = int(size_raw)
            except (TypeError, ValueError):
                pass

            releases.append(
                Release(
                    indexer="torrentio",
                    title=t.get("title") or t.get("name") or "",
                    infohash=torrent_hash.lower(),
                    magnet=magnet,
                    media_type=media_type,
                    seeds=int(t.get("seeders") or t.get("seeds") or 0),
                    peers=int(t.get("peers") or t.get("leechers") or 0),
                    size_bytes=size_bytes,
                    quality=t.get("quality") or t.get("resolution"),
                    year=_to_int(t.get("year")),
                    season=_to_int(t.get("season")),
                    episode=_to_int(t.get("episode")),
                    imdb_id=t.get("imdb_id"),
                    tmdb_id=_to_int(t.get("tmdb_id")),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("Skipping Torrentio torrent: %s", exc)
            continue

    return releases


def _build_magnet(torrent_hash: str, trackers: list[str]) -> str:
    """Build a magnet URI from a torrent hash and tracker list."""
    hash_part = torrent_hash.lower().strip()
    tracker_params = "&".join(f"tr={t}" for t in trackers)
    return f"magnet:?xt=urn:btih:{hash_part}&{tracker_params}"


def _to_int(v: Any) -> int | None:
    """Convert a value to int, returning None on failure."""
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None
