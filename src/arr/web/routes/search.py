from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi import Query as FastQuery

from arr.core.models import MediaType
from arr.core.parsing import explain
from arr.log import get_logger
from arr.metadata.imdb import ImdbClient
from arr.metadata.tvmaze import TvmazeClient
from arr.pipeline import search_candidates

logger = get_logger("search")
router = APIRouter(prefix="/api", tags=["search"])


@router.get("/search/movies")
async def search_movies(
    request: Request, q: str = FastQuery(..., min_length=1)
) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    imdb = ImdbClient(cfg)
    logger.info(f"Searching movies (IMDb): '{q}'")
    try:
        results = await asyncio.to_thread(imdb.search_movies, q)
        logger.info(f"Found {len(results)} movie result(s) for '{q}'")
        return results
    except Exception as e:
        logger.error(f"Movie search failed for '{q}': {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {e}") from e


@router.get("/search/tv")
async def search_tv(
    request: Request, q: str = FastQuery(..., min_length=1)
) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    tvmaze = TvmazeClient(cfg)
    logger.info(f"Searching TV shows (TVMaze): '{q}'")
    try:
        results = await asyncio.to_thread(tvmaze.search_tv_shows, q)
        logger.info(f"Found {len(results)} TV show result(s) for '{q}'")
        return results
    except Exception as e:
        logger.error(f"TV search failed for '{q}': {e}")
        raise HTTPException(status_code=500, detail=f"Search failed: {e}") from e


@router.get("/tv/{show_id}/details")
async def get_tv_details(request: Request, show_id: int) -> dict[str, Any]:
    cfg = request.app.state.cfg
    tvmaze = TvmazeClient(cfg)
    logger.info(f"Fetching TV show details for show ID {show_id}")
    try:
        series = await asyncio.to_thread(tvmaze.tv_details, show_id)
        raw_episodes = await asyncio.to_thread(tvmaze._get, f"/shows/{show_id}/episodes")
        episodes_list = raw_episodes if isinstance(raw_episodes, list) else []

        seasons_dict: dict[int, list[dict[str, Any]]] = {}
        for ep in episodes_list:
            s_num = int(ep.get("season") or 0)
            if s_num == 0:
                continue
            if s_num not in seasons_dict:
                seasons_dict[s_num] = []
            seasons_dict[s_num].append(
                {
                    "episode_number": int(ep.get("number") or 0),
                    "name": str(ep.get("name") or ""),
                    "air_date": ep.get("airdate"),
                }
            )

        seasons = [
            {"season_number": s, "episodes": seasons_dict[s]}
            for s in sorted(seasons_dict.keys())
        ]
        logger.info(f"Loaded {len(seasons)} season(s) for '{series.title}'")

        return {
            "id": series.tmdb_id,
            "title": series.title,
            "year": series.year,
            "imdb_id": series.imdb_id,
            "tvdb_id": series.tvdb_id,
            "status": series.status,
            "seasons": seasons,
        }
    except Exception as e:
        logger.error(f"Failed to fetch show details for ID {show_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch show details: {e}") from e


@router.get("/releases/movie")
async def get_movie_releases(
    request: Request,
    title: str = FastQuery(..., min_length=1),
    year: int | None = None,
    imdb_id: str | None = None,
) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    logger.info(f"Searching movie releases: '{title}' (year={year}, imdb_id={imdb_id})")
    try:
        releases, scored_list, _q = await search_candidates(
            MediaType.MOVIE, title, cfg, year=year, imdb_id=imdb_id, title=title
        )
        scored_map = {s.release.infohash: s for s in scored_list}

        out: list[dict[str, Any]] = []
        for r in releases:
            s = scored_map.get(r.infohash)
            if s and isinstance(s.score, dict):
                score_val = max(
                    0, 1000 - s.score.get("resolution_rank", 10) * 100 + s.score.get("seeders", 0)
                )
            elif s and isinstance(s.score, (int, float)):
                score_val = s.score
            else:
                score_val = 0
            reasons = []
            if s:
                try:
                    reasons = [explain([s])]
                except Exception:
                    reasons = [f"Score: {score_val}"]
            out.append(
                {
                    "indexer": r.indexer,
                    "title": r.title,
                    "infohash": r.infohash,
                    "magnet": r.magnet,
                    "seeds": r.seeds,
                    "peers": r.peers,
                    "size_bytes": r.size_bytes,
                    "resolution": r.resolution or r.quality,
                    "codec": r.codec,
                    "source": r.source,
                    "score": score_val,
                    "is_pack": r.is_pack,
                    "reasons": reasons,
                }
            )
        logger.info(f"Found {len(out)} release candidate(s) for movie '{title}'")
        return out
    except Exception as e:
        logger.error(f"Failed to search movie releases for '{title}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to search releases: {e}") from e


@router.get("/releases/tv")
async def get_tv_releases(
    request: Request,
    title: str = FastQuery(..., min_length=1),
    season: int | None = None,
    episode: int | None = None,
    pack: bool = False,
) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    ep_str = (
        f"S{season:02d}E{episode:02d}"
        if season is not None and episode is not None
        else (f"Season {season}" if season is not None else "all")
    )
    logger.info(f"Searching TV releases: '{title}' ({ep_str}, pack={pack})")
    try:
        releases, scored_list, _q = await search_candidates(
            MediaType.TV,
            title,
            cfg,
            season=season,
            episode=episode,
            title=title,
        )
        scored_map = {s.release.infohash: s for s in scored_list}

        out: list[dict[str, Any]] = []
        for r in releases:
            s = scored_map.get(r.infohash)
            if s and isinstance(s.score, dict):
                score_val = max(
                    0, 1000 - s.score.get("resolution_rank", 10) * 100 + s.score.get("seeders", 0)
                )
            elif s and isinstance(s.score, (int, float)):
                score_val = s.score
            else:
                score_val = 0
            reasons = []
            if s:
                try:
                    reasons = [explain([s])]
                except Exception:
                    reasons = [f"Score: {score_val}"]
            out.append(
                {
                    "indexer": r.indexer,
                    "title": r.title,
                    "infohash": r.infohash,
                    "magnet": r.magnet,
                    "seeds": r.seeds,
                    "peers": r.peers,
                    "size_bytes": r.size_bytes,
                    "resolution": r.resolution or r.quality,
                    "codec": r.codec,
                    "source": r.source,
                    "score": score_val,
                    "is_pack": r.is_pack,
                    "reasons": reasons,
                }
            )
        logger.info(f"Found {len(out)} release candidate(s) for TV '{title}' ({ep_str})")
        return out
    except Exception as e:
        logger.error(f"Failed to search TV releases for '{title}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to search releases: {e}") from e
