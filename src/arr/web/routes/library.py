from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from arr.interactive.library_view import get_library_movies, get_library_shows
from arr.log import get_logger
from arr.pipeline import _db

logger = get_logger("library")
router = APIRouter(prefix="/api", tags=["library"])


@router.get("/library")
async def get_library(request: Request) -> dict[str, Any]:
    cfg = request.app.state.cfg
    lib_root = Path(str(cfg.get("library_root", "downloads"))).resolve()
    movies_dir = lib_root / "movies"
    tv_dir = lib_root / "tv-shows"

    logger.info(f"Scanning media library root: {lib_root}")
    try:
        raw_movies = await asyncio.to_thread(get_library_movies, movies_dir, cfg)
        raw_shows = await asyncio.to_thread(get_library_shows, tv_dir, cfg)

        # Convert Path objects to strings for JSON
        movies = [
            {
                "title": m["title"],
                "path": str(m["path"]),
                "file_count": m["file_count"],
                "size_mb": round(m["size_mb"], 1),
                "primary_ext": m["primary_ext"],
            }
            for m in raw_movies
        ]
        shows = [
            {
                "title": s["title"],
                "path": str(s["path"]),
                "seasons_count": s["seasons_count"],
                "episodes_count": s["episodes_count"],
                "monitored_count": s.get("monitored_count", 0),
                "missing": s.get("missing", []),
            }
            for s in raw_shows
        ]
        return {"movies": movies, "shows": shows}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan library: {e}") from e


@router.get("/series")
async def list_monitored_series(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    db = _db(cfg)
    try:
        monitored = db.list_monitored()
        out = []
        for s in monitored:
            tmdb_id = int(s["tmdb_id"])
            episodes = db.episodes_for_series(tmdb_id)
            total_eps = len(episodes)
            imported_eps = sum(1 for ep in episodes if ep.get("state") == "imported")
            out.append(
                {
                    "id": s["id"],
                    "tmdb_id": tmdb_id,
                    "imdb_id": s.get("imdb_id"),
                    "title": s["title"],
                    "status": s.get("status"),
                    "quality": s.get("quality"),
                    "total_episodes": total_eps,
                    "imported_episodes": imported_eps,
                    "missing_episodes": max(0, total_eps - imported_eps),
                }
            )
        return out
    finally:
        db.close()


class MonitorSeriesRequest(BaseModel):
    tmdb_id: int
    title: str
    imdb_id: str | None = None
    status: str = "Returning Series"
    quality: str | None = None


@router.post("/series/monitor")
async def monitor_series(request: Request, body: MonitorSeriesRequest) -> dict[str, Any]:
    cfg = request.app.state.cfg
    db = _db(cfg)
    try:
        series_id = db.add_monitored(
            tmdb_id=body.tmdb_id,
            title=body.title,
            imdb_id=body.imdb_id,
            status=body.status,
            quality=body.quality,
        )
        logger.info(
            f"Added series to monitor list: '{body.title}' (id={series_id}, tmdb={body.tmdb_id})"
        )
        return {"status": "monitored", "id": series_id, "title": body.title}
    finally:
        db.close()


@router.delete("/series/{series_id}")
async def unmonitor_series(request: Request, series_id: int) -> dict[str, str]:
    cfg = request.app.state.cfg
    db = _db(cfg)
    try:
        db.remove_monitored(series_id)
        logger.info(f"Removed series ID {series_id} from monitor list")
        return {"status": "unmonitored", "id": str(series_id)}
    finally:
        db.close()
