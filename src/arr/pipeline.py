from __future__ import annotations

import asyncio
import sys

from arr.config.settings import Config
from arr.core.models import MediaType, QualityProfile, Query, Release
from arr.core.parsing import explain, rank
from arr.indexers import build_adapters
from arr.metadata.tmdb import TmdbClient, TmdbError, degrade

__all__ = [
    "search",
    "download_movie",
    "download_tv",
    "series_add",
    "series_list",
    "series_remove",
    "series_check",
    "list_queue",
    "get_status",
    "cancel_download",
    "import_download",
    "run_daemon",
]


async def search(
    media_type: MediaType,
    query: str,
    cfg: Config,
    season: int | None = None,
    episode: int | None = None,
    explain_mode: bool = False,
) -> list[Release]:
    q = Query(media_type=media_type, text=query, season=season, episode=episode)
    # TMDB resolve (best effort)
    try:
        tmdb = TmdbClient(cfg)
        if media_type == MediaType.MOVIE:
            m = tmdb.search_movie(query)
            if m:
                q.tmdb_id = m.get("id")
                q.title = m.get("title")
        else:
            s = tmdb.search_tv(query)
            if s:
                q.tmdb_id = s.get("id")
                q.title = s.get("name")
                try:
                    ext = tmdb.tv_external_ids(s["id"])
                    q.imdb_id = ext.get("imdb_id")
                except TmdbError:
                    pass
    except TmdbError as e:
        degrade(query)
        print(f"warning: TMDB lookup failed: {e}", file=sys.stderr)

    adapters = [a for a in build_adapters(cfg) if a.supports(media_type)]
    search_text = q.title or query
    q.text = search_text

    async def _one(a):
        try:
            return await asyncio.wait_for(a.search(q), timeout=30.0)
        except Exception as e:
            print(f"warning: indexer {a.name} failed: {e}", file=sys.stderr)
            return []

    results = await asyncio.gather(*[_one(a) for a in adapters])
    releases: list[Release] = []
    for group in results:
        releases.extend(group)

    profile = QualityProfile(
        resolutions=list(cfg.get("resolutions") or ["2160p", "1080p", "720p"]),
        min_seeders=int(cfg.get("min_seeders", 1)),
    )
    scored = rank(releases, q, profile, cfg.values)
    if explain_mode:
        print(explain(scored), file=sys.stderr)
    return [s.release for s in scored if s.rejected is None]


async def download_movie(query, cfg, **kwargs):
    raise NotImplementedError


async def download_tv(query, cfg, **kwargs):
    raise NotImplementedError


async def series_add(query, cfg):
    raise NotImplementedError


def series_list(cfg):
    raise NotImplementedError


def series_remove(series_id, cfg, delete_files=False):
    raise NotImplementedError


async def series_check(series_id, cfg):
    raise NotImplementedError


def list_queue(cfg):
    raise NotImplementedError


def get_status(download_id, cfg):
    raise NotImplementedError


async def cancel_download(download_id, cfg, delete_data=False):
    raise NotImplementedError


async def import_download(download_id, cfg, overwrite=False):
    raise NotImplementedError


async def run_daemon(cfg):
    raise NotImplementedError
