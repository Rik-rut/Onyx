from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, model_validator

from arr.core.models import MediaType, Release
from arr.log import get_logger
from arr.pipeline import _rpc, download_magnet, enqueue_release, remove_download_and_files
from arr.transmission.process import RpcClient

logger = get_logger("queue")
router = APIRouter(prefix="/api/queue", tags=["queue"])

STATUS_NAMES = {
    0: "Paused",
    1: "Check Pending",
    2: "Checking",
    3: "Queue Pending",
    4: "Downloading",
    5: "Seed Pending",
    6: "Seeding",
}


def _get_rpc(cfg: Any) -> RpcClient:
    return _rpc(cfg)


def _coerce_tid(tid: str) -> int | str:
    s = str(tid).strip()
    return int(s) if s.isdigit() else s


async def fetch_merged_queue(cfg: Any, rpc: Any = None) -> list[dict[str, Any]]:
    """Merge tracked downloads from SQLite with live torrents from Transmission RPC."""
    from arr.pipeline import list_queue

    try:
        db_items = list_queue(cfg)
    except Exception:
        db_items = []

    active_rpc = rpc
    if active_rpc is None:
        try:
            active_rpc = _get_rpc(cfg)
        except Exception:
            active_rpc = None

    rpc_torrents: list[dict[str, Any]] = []
    if active_rpc is not None:
        try:
            rpc_torrents = await active_rpc.list_torrents()
        except Exception:
            rpc_torrents = []

    rpc_by_hash = {
        str(t.get("hashString", "")).lower(): t for t in rpc_torrents if t.get("hashString")
    }

    out: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for item in db_items:
        h = str(item.get("infohash", "")).lower()
        if not h:
            continue
        seen_hashes.add(h)
        t = rpc_by_hash.get(h)
        state = str(item.get("state") or "unknown").lower()

        if t is not None:
            p_done = float(t.get("percentDone") or 0.0)
            status_val = int(t.get("status") or 0)
            out.append(
                {
                    "id": t.get("id"),
                    "infohash": t.get("hashString", h),
                    "name": t.get("name") or item.get("title") or h[:8],
                    "progress": round(p_done * 100, 1),
                    "status_code": status_val,
                    "status": STATUS_NAMES.get(status_val, f"Status {status_val}"),
                    "rate_download": int(t.get("rateDownload") or 0),
                    "rate_upload": int(t.get("rateUpload") or 0),
                    "eta": int(t.get("eta") or -1),
                    "total_size": int(t.get("totalSize") or 0),
                    "media_type": item.get("media_type"),
                }
            )
        else:
            if state in ("imported", "completed"):
                p_done = 100.0
                status_code = 6
                status_label = "Imported" if state == "imported" else "Completed"
            elif state == "downloading":
                p_done = 0.0
                status_code = 4
                status_label = "Downloading"
            elif state == "queued":
                p_done = 0.0
                status_code = 0
                status_label = "Queued"
            elif state == "failed":
                p_done = 0.0
                status_code = -1
                status_label = "Failed"
            elif state == "skipped":
                p_done = 0.0
                status_code = -1
                status_label = "Cancelled"
            else:
                p_done = 0.0
                status_code = 3
                status_label = state.capitalize()

            out.append(
                {
                    "id": h,
                    "infohash": h,
                    "name": item.get("title") or h[:8],
                    "progress": p_done,
                    "status_code": status_code,
                    "status": status_label,
                    "rate_download": 0,
                    "rate_upload": 0,
                    "eta": -1,
                    "total_size": 0,
                    "media_type": item.get("media_type"),
                }
            )

    for t in rpc_torrents:
        h = str(t.get("hashString", "")).lower()
        if h in seen_hashes:
            continue
        p_done = float(t.get("percentDone") or 0.0)
        status_val = int(t.get("status") or 0)
        out.append(
            {
                "id": t.get("id"),
                "infohash": t.get("hashString", ""),
                "name": t.get("name", ""),
                "progress": round(p_done * 100, 1),
                "status_code": status_val,
                "status": STATUS_NAMES.get(status_val, f"Status {status_val}"),
                "rate_download": int(t.get("rateDownload") or 0),
                "rate_upload": int(t.get("rateUpload") or 0),
                "eta": int(t.get("eta") or -1),
                "total_size": int(t.get("totalSize") or 0),
                "media_type": None,
            }
        )

    return out


@router.get("")
async def get_queue(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    return await fetch_merged_queue(cfg)


@router.post("/{torrent_id}/pause")
async def pause_torrent(request: Request, torrent_id: str) -> dict[str, str]:
    cfg = request.app.state.cfg
    cid = _coerce_tid(torrent_id)
    try:
        rpc = _get_rpc(cfg)
        logger.info(f"Pausing torrent {cid}")
        await rpc.stop(cid)
        return {"status": "paused", "id": str(torrent_id)}
    except Exception as e:
        logger.error(f"Failed to pause torrent {cid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to pause torrent: {e}") from e


@router.post("/{torrent_id}/resume")
async def resume_torrent(request: Request, torrent_id: str) -> dict[str, str]:
    cfg = request.app.state.cfg
    cid = _coerce_tid(torrent_id)
    try:
        rpc = _get_rpc(cfg)
        logger.info(f"Resuming torrent {cid}")
        await rpc.start(cid)
        return {"status": "resumed", "id": str(torrent_id)}
    except Exception as e:
        logger.error(f"Failed to resume torrent {cid}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to resume torrent: {e}") from e


@router.post("/{torrent_id}/delete")
@router.delete("/{torrent_id}")
async def delete_torrent(request: Request, torrent_id: str) -> dict[str, Any]:
    """Remove a queue item: torrent, downloaded files, and local queue state (R1.1/R1.2)."""
    cfg = request.app.state.cfg
    logger.info(f"Removing torrent {torrent_id} and its downloaded files")
    try:
        result = await remove_download_and_files(str(torrent_id), cfg)
        logger.info(
            f"Removed torrent {torrent_id} "
            f"[infohash={str(result['infohash'])[:12]}, "
            f"files={len(result['deleted_paths'])}, "
            f"torrent_removed={result['torrent_removed']}, "
            f"rpc_error={result['rpc_error']}]"
        )
        return {
            "status": "deleted",
            "id": str(torrent_id),
            "infohash": str(result["infohash"]),
            "torrent_removed": str(result["torrent_removed"]).lower(),
            "files_removed": str(len(result["deleted_paths"])),
            "rpc_error": str(result["rpc_error"] or ""),
        }
    except Exception as e:
        logger.error(f"Failed to remove torrent {torrent_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to remove torrent: {e}") from e


@router.post("/{torrent_id}/priority/up")
async def priority_up(request: Request, torrent_id: str) -> dict[str, str]:
    cfg = request.app.state.cfg
    cid = _coerce_tid(torrent_id)
    try:
        rpc = _get_rpc(cfg)
        logger.info(f"Moving torrent {cid} up in queue")
        await rpc.queue_move_up(cid)
        return {"status": "moved_up", "id": str(torrent_id)}
    except Exception as e:
        logger.error(f"Failed to move torrent {cid} up: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to move torrent up: {e}") from e


@router.post("/{torrent_id}/priority/down")
async def priority_down(request: Request, torrent_id: str) -> dict[str, str]:
    cfg = request.app.state.cfg
    cid = _coerce_tid(torrent_id)
    try:
        rpc = _get_rpc(cfg)
        logger.info(f"Moving torrent {cid} down in queue")
        await rpc.queue_move_down(cid)
        return {"status": "moved_down", "id": str(torrent_id)}
    except Exception as e:
        logger.error(f"Failed to move torrent {cid} down: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to move torrent down: {e}") from e


class DownloadReleaseRequest(BaseModel):
    indexer: str
    title: str
    infohash: str
    magnet: str
    media_type: str
    seeds: int = 0
    peers: int = 0
    size_bytes: int = 0
    resolution: str | None = None
    codec: str | None = None
    source: str | None = None
    is_pack: bool = False
    display_title: str | None = None
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    imdb_id: str | None = None
    tmdb_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_identifiers(cls, data: Any) -> Any:
        if isinstance(data, dict):
            raw_tmdb = data.get("tmdb_id")
            raw_imdb = data.get("imdb_id")
            # If tmdb_id was passed an IMDb format string (e.g. "tt1302011")
            if isinstance(raw_tmdb, str) and raw_tmdb.startswith("tt"):
                if not raw_imdb:
                    data["imdb_id"] = raw_tmdb
                data["tmdb_id"] = None
            elif raw_tmdb is not None:
                try:
                    data["tmdb_id"] = int(raw_tmdb)
                except (ValueError, TypeError):
                    data["tmdb_id"] = None
        return data


@router.post("/download/release")
async def download_release(request: Request, body: DownloadReleaseRequest) -> dict[str, Any]:
    cfg = request.app.state.cfg
    mtype = MediaType.MOVIE if body.media_type == "movie" else MediaType.TV
    release = Release(
        indexer=body.indexer,
        title=body.title,
        infohash=body.infohash,
        magnet=body.magnet,
        media_type=mtype,
        seeds=body.seeds,
        peers=body.peers,
        size_bytes=body.size_bytes,
        resolution=body.resolution,
        codec=body.codec,
        source=body.source,
        is_pack=body.is_pack,
        year=body.year,
        season=body.season,
        episode=body.episode,
        imdb_id=body.imdb_id,
        tmdb_id=body.tmdb_id,
    )
    logger.info(
        f"Queuing release for download: '{body.title}' ({body.indexer}) "
        f"[hash={body.infohash[:8]}..., type={body.media_type}, "
        f"year={body.year}, imdb={body.imdb_id}, tmdb={body.tmdb_id}]"
    )
    try:
        ok, res = await enqueue_release(
            release,
            cfg,
            media_type=body.media_type,
            season=body.season,
            episode=body.episode,
            imdb_id=body.imdb_id,
            tmdb_id=body.tmdb_id,
            year=body.year,
        )
        if not ok:
            logger.error(f"Failed to enqueue release '{body.title}': {res}")
            raise HTTPException(status_code=500, detail=str(res))
        logger.info(f"Release successfully queued: {res}")
        return {"status": "queued", "result": str(res), "infohash": release.infohash}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to enqueue release '{body.title}': {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enqueue release: {e}") from e


class DownloadMagnetRequest(BaseModel):
    magnet: str


@router.post("/download/magnet")
async def download_magnet_api(request: Request, body: DownloadMagnetRequest) -> dict[str, Any]:
    cfg = request.app.state.cfg
    logger.info(f"Ingesting raw magnet URI: {body.magnet[:60]}...")
    try:
        res = await download_magnet(body.magnet, cfg)
        logger.info(f"Magnet successfully ingested: {res}")
        return {"status": "queued", "result": str(res)}
    except Exception as e:
        logger.error(f"Failed to ingest magnet: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to ingest magnet: {e}") from e


@router.post("/import")
async def trigger_import(request: Request) -> dict[str, str]:
    cfg = request.app.state.cfg
    logger.info("Triggering manual library import scan")
    try:
        from arr.pipeline import _db, _poll_and_import, _sync_rpc_state

        db = _db(cfg)
        try:
            _sync_rpc_state(cfg, db)
            count = _poll_and_import(cfg, db)
            logger.info(f"Manual import scan completed ({count} item(s) imported)")
            return {"status": "import_completed", "imported_count": str(count)}
        finally:
            db.close()
    except Exception as e:
        logger.error(f"Import failed: {e}")
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e
