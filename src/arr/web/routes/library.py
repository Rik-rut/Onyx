from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from arr.db import DB
from arr.interactive.library_view import get_library_movies, get_library_shows
from arr.log import get_logger
from arr.metadata.matching import pick_match
from arr.metadata.posters import PosterResolver
from arr.metadata.tvmaze import TvmazeClient
from arr.pipeline import (
    _DISK_HASH_PREFIX,
    _db,
    _delete_media_path,
    _find_monitored,
    _library_root,
    _parse_title_year,
    _rpc,
    remove_download_and_files,
)

logger = get_logger("library")
router = APIRouter(prefix="/api", tags=["library"])

LIBRARY_FOLDERS = {"movie": "movies", "tv": "tv-shows"}


class LibraryItemRequest(BaseModel):
    kind: Literal["movie", "tv"]
    name: str
    confirm: bool = False


class MonitorSeriesRequest(BaseModel):
    tmdb_id: int
    title: str
    imdb_id: str | None = None
    status: str = "Returning Series"
    quality: str | None = None


def _norm(path: Path) -> str:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return os.path.normcase(str(resolved))


def _inside(path: object, entry: Path) -> bool:
    """Is `path` the library entry itself, or something below it?"""
    target = _norm(entry)
    candidate = _norm(Path(str(path)))
    return candidate == target or candidate.startswith(target + os.sep)


def _entry_path(cfg: Any, kind: str, name: str) -> Path:
    """The library folder or file called `name`; any other path is refused."""
    if kind not in LIBRARY_FOLDERS or not name or name.startswith(".") or Path(name).name != name:
        raise HTTPException(status_code=404, detail="No such library entry.")
    entry = _library_root(cfg) / LIBRARY_FOLDERS[kind] / name
    if not entry.exists():
        raise HTTPException(status_code=404, detail="No such library entry.")
    return entry


def _title_and_year(entry: Path) -> tuple[str, int | None]:
    return _parse_title_year(entry.stem if entry.is_file() else entry.name)


def _records_for(db: DB, entry: Path) -> list[dict[str, Any]]:
    """Download records whose imported or raw files sit inside this library entry."""
    keys = ("destination_path", "content_path")
    return [
        rec
        for rec in db.list_downloads()
        if any(rec.get(key) and _inside(rec[key], entry) for key in keys)
    ]


def _infohashes_for(cfg: Any, entry: Path) -> list[str]:
    db = _db(cfg)
    try:
        hashes = {str(r["infohash"]).lower() for r in _records_for(db, entry) if r.get("infohash")}
        return sorted(hashes)
    finally:
        db.close()


def _poster_url(kind: str, name: str) -> str:
    return f"/api/library/poster?kind={kind}&name={quote(name, safe='')}"


async def _live_torrents(cfg: Any) -> dict[str, dict[str, Any]] | None:
    """Transmission's torrents keyed by infohash, or None when Transmission is unreachable."""
    try:
        rpc = await asyncio.to_thread(_rpc, cfg)
        torrents = await rpc.list_torrents()
    except Exception as e:
        logger.debug(f"Transmission unreachable while reading the library: {e}")
        return None
    return {str(t.get("hashString", "")).lower(): t for t in torrents if t.get("hashString")}


def _library_payload(
    cfg: Any,
    live: dict[str, dict[str, Any]],
    raw_movies: list[dict[str, Any]],
    raw_shows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    db = _db(cfg)
    try:
        movies: list[dict[str, Any]] = []
        for raw in raw_movies:
            entry = Path(str(raw["path"]))
            title, year = _title_and_year(entry)
            records = _records_for(db, entry)
            movies.append(
                {
                    "name": entry.name,
                    "title": title or entry.name,
                    "year": year,
                    "path": str(entry),
                    "file_count": raw["file_count"],
                    "size_mb": round(raw["size_mb"], 1),
                    "primary_ext": raw["primary_ext"],
                    "imdb_id": next((r["imdb_id"] for r in records if r.get("imdb_id")), None),
                    "seeding": any(_hash_live(r, live) for r in records),
                    "poster": _poster_url("movie", entry.name),
                }
            )
        shows: list[dict[str, Any]] = []
        for raw in raw_shows:
            entry = Path(str(raw["path"]))
            title, year = _title_and_year(entry)
            row = _find_monitored(db, title)
            records = _records_for(db, entry)
            shows.append(
                {
                    "name": entry.name,
                    "title": title or entry.name,
                    "year": year,
                    "path": str(entry),
                    "seasons_count": raw["seasons_count"],
                    "episodes_count": raw["episodes_count"],
                    "monitored_count": raw.get("monitored_count", 0),
                    "missing": raw.get("missing", []),
                    "monitored": row is not None,
                    "monitored_id": int(row["id"]) if row else None,
                    "tmdb_id": int(row["tmdb_id"]) if row else None,
                    "seeding": any(_hash_live(r, live) for r in records),
                    "poster": _poster_url("tv", entry.name),
                }
            )
        return movies, shows
    finally:
        db.close()


def _hash_live(rec: dict[str, Any], live: dict[str, dict[str, Any]]) -> bool:
    return bool(rec.get("infohash")) and str(rec["infohash"]).lower() in live


def _cover_url(cfg: Any, kind: str, entry: Path) -> str:
    title, year = _title_and_year(entry)
    resolver = PosterResolver(cfg)
    db = _db(cfg)
    try:
        if kind == "movie":
            imdb = next((r["imdb_id"] for r in _records_for(db, entry) if r.get("imdb_id")), None)
            return resolver.movie_poster(title, year, imdb)
        row = _find_monitored(db, title)
        return resolver.show_poster(title, year, int(row["tmdb_id"]) if row else None)
    finally:
        db.close()


def _untrack_for_delete(cfg: Any, entry: Path) -> bool:
    """Stop tracking a show whose files are being deleted, and forget its episode rows."""
    title, _ = _title_and_year(entry)
    db = _db(cfg)
    try:
        row = _find_monitored(db, title)
        if row is None:
            return False
        tmdb_id = int(row["tmdb_id"])
        for ep in db.episodes_for_series(tmdb_id):
            if ep.get("path") and _inside(ep["path"], entry):
                db.delete_episode(tmdb_id, int(ep["season"]), int(ep["episode"]))
        db.remove_monitored(int(row["id"]))
        return True
    finally:
        db.close()


def _untrack(cfg: Any, title: str) -> dict[str, Any]:
    db = _db(cfg)
    try:
        row = _find_monitored(db, title)
        if row is None:
            raise HTTPException(status_code=404, detail="This show is not tracked.")
        db.untrack_series(int(row["id"]))
        logger.info(f"Stopped tracking '{row['title']}' (id={row['id']})")
        return {"status": "untracked", "id": int(row["id"]), "title": row["title"]}
    finally:
        db.close()


def _track(cfg: Any, title: str, year: int | None) -> dict[str, Any]:
    client = TvmazeClient(cfg)
    try:
        candidates = client.search_tv_shows(title)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"TVMaze is not reachable: {e}") from e
    match = pick_match(candidates, title, year)
    if match is None:
        raise HTTPException(status_code=404, detail=f"No TVMaze match for '{title}'.")
    series = client.tv_details(int(match["id"]))
    db = _db(cfg)
    try:
        series_id = db.add_monitored(
            tmdb_id=series.tmdb_id,
            title=series.title,
            imdb_id=series.imdb_id,
            status=series.status,
            quality=None,
        )
    finally:
        db.close()
    logger.info(f"Tracking '{series.title}' (id={series_id}, tmdb={series.tmdb_id})")
    return {"status": "tracked", "id": series_id, "title": series.title}


@router.get("/library")
async def get_library(request: Request) -> dict[str, Any]:
    cfg = request.app.state.cfg
    lib_root = Path(str(cfg.get("library_root", "downloads"))).resolve()
    movies_dir = lib_root / "movies"
    tv_dir = lib_root / "tv-shows"

    logger.info(f"Scanning media library root: {lib_root}")
    try:
        from arr.pipeline import cleanup_duplicate_folders, sync_disk_library

        # R2.3/R3.1: a rescan collapses leftover raw folders and re-indexes disk media.
        await asyncio.to_thread(cleanup_duplicate_folders, cfg)
        sync_stats = await asyncio.to_thread(sync_disk_library, cfg)
        raw_movies = await asyncio.to_thread(get_library_movies, movies_dir, cfg)
        raw_shows = await asyncio.to_thread(get_library_shows, tv_dir, cfg)
        live = await _live_torrents(cfg) or {}
        movies, shows = await asyncio.to_thread(_library_payload, cfg, live, raw_movies, raw_shows)
        return {"movies": movies, "shows": shows, "sync": sync_stats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to scan library: {e}") from e


@router.get("/library/poster")
async def library_poster(
    request: Request, kind: Literal["movie", "tv"], name: str
) -> RedirectResponse:
    """Redirect to the cover art of a library entry; 404 when none can be found."""
    cfg = request.app.state.cfg
    entry = _entry_path(cfg, kind, name)
    url = await asyncio.to_thread(_cover_url, cfg, kind, entry)
    if not url:
        raise HTTPException(status_code=404, detail="No cover art found.")
    return RedirectResponse(url, status_code=302)


@router.post("/library/delete")
async def delete_library_item(request: Request, body: LibraryItemRequest) -> dict[str, Any]:
    """Delete a title's files, its Transmission torrent and its records (after confirmation)."""
    if not body.confirm:
        raise HTTPException(
            status_code=422,
            detail='Deleting a title removes its files: resend with {"confirm": true}.',
        )
    cfg = request.app.state.cfg
    entry = _entry_path(cfg, body.kind, body.name)
    infohashes = await asyncio.to_thread(_infohashes_for, cfg, entry)
    real_torrents = [h for h in infohashes if not h.startswith(_DISK_HASH_PREFIX)]
    if real_torrents and await _live_torrents(cfg) is None:
        raise HTTPException(
            status_code=503,
            detail="Transmission is not reachable, so nothing was deleted. Try again shortly.",
        )

    torrents_removed = 0
    files_removed = 0
    for infohash in infohashes:
        result = await remove_download_and_files(infohash, cfg, delete_files=True)
        torrents_removed += int(bool(result.get("torrent_removed")))
        files_removed += len(result.get("deleted_paths") or [])

    if await asyncio.to_thread(_delete_media_path, entry, cfg):
        files_removed += 1
    untracked = False
    if body.kind == "tv":
        untracked = await asyncio.to_thread(_untrack_for_delete, cfg, entry)
    logger.info(
        f"Deleted library entry '{body.name}' "
        f"({torrents_removed} torrent(s), {files_removed} path(s))"
    )
    return {
        "status": "deleted",
        "name": body.name,
        "torrents_removed": torrents_removed,
        "files_removed": files_removed,
        "untracked": untracked,
    }


@router.post("/library/remove-seed")
async def remove_library_seed(request: Request, body: LibraryItemRequest) -> dict[str, Any]:
    """Stop seeding a title: its torrent leaves Transmission, its files stay in the library."""
    cfg = request.app.state.cfg
    entry = _entry_path(cfg, body.kind, body.name)
    infohashes = set(await asyncio.to_thread(_infohashes_for, cfg, entry))
    rpc = await asyncio.to_thread(_rpc, cfg)
    try:
        torrents = await rpc.list_torrents()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail="Transmission is not reachable, so seeding cannot be changed.",
        ) from e
    removed = 0
    for torrent in torrents:
        if str(torrent.get("hashString", "")).lower() in infohashes:
            await rpc.remove(torrent["id"], delete_data=False)
            removed += 1
    return {"status": "seed_removed" if removed else "not_seeding", "removed": removed}


@router.post("/library/track")
async def track_library_show(request: Request, body: LibraryItemRequest) -> dict[str, Any]:
    if body.kind != "tv":
        raise HTTPException(status_code=400, detail="Only TV shows can be tracked.")
    cfg = request.app.state.cfg
    entry = _entry_path(cfg, "tv", body.name)
    title, year = _title_and_year(entry)
    return await asyncio.to_thread(_track, cfg, title, year)


@router.post("/library/untrack")
async def untrack_library_show(request: Request, body: LibraryItemRequest) -> dict[str, Any]:
    if body.kind != "tv":
        raise HTTPException(status_code=400, detail="Only TV shows can be tracked.")
    cfg = request.app.state.cfg
    entry = _entry_path(cfg, "tv", body.name)
    title, _ = _title_and_year(entry)
    return await asyncio.to_thread(_untrack, cfg, title)


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
        db.untrack_series(series_id)
        logger.info(f"Stopped monitoring series ID {series_id}")
        return {"status": "unmonitored", "id": str(series_id)}
    finally:
        db.close()
