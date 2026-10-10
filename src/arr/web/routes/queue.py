from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, model_validator

from arr.core.models import MediaType, Release
from arr.pipeline import _rpc, download_magnet, enqueue_release
from arr.transmission.process import RpcClient

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


@router.get("")
async def get_queue(request: Request) -> list[dict[str, Any]]:
    cfg = request.app.state.cfg
    try:
        rpc = _get_rpc(cfg)
        torrents = await rpc.list_torrents()
        out = []
        for t in torrents:
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
                }
            )
        return out
    except Exception:
        # If transmission daemon is temporarily offline or unreachable, return empty list
        return []


@router.post("/{torrent_id}/pause")
async def pause_torrent(request: Request, torrent_id: int) -> dict[str, str]:
    cfg = request.app.state.cfg
    try:
        rpc = _get_rpc(cfg)
        await rpc.stop(torrent_id)
        return {"status": "paused", "id": str(torrent_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to pause torrent: {e}") from e


@router.post("/{torrent_id}/resume")
async def resume_torrent(request: Request, torrent_id: int) -> dict[str, str]:
    cfg = request.app.state.cfg
    try:
        rpc = _get_rpc(cfg)
        await rpc.start(torrent_id)
        return {"status": "resumed", "id": str(torrent_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to resume torrent: {e}") from e


@router.post("/{torrent_id}/delete")
async def delete_torrent(request: Request, torrent_id: int) -> dict[str, str]:
    cfg = request.app.state.cfg
    try:
        rpc = _get_rpc(cfg)
        await rpc.remove(torrent_id, delete_data=False)
        return {"status": "deleted", "id": str(torrent_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to remove torrent: {e}") from e


@router.post("/{torrent_id}/priority/up")
async def priority_up(request: Request, torrent_id: int) -> dict[str, str]:
    cfg = request.app.state.cfg
    try:
        rpc = _get_rpc(cfg)
        await rpc.queue_move_up(torrent_id)
        return {"status": "moved_up", "id": str(torrent_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to move torrent up: {e}") from e


@router.post("/{torrent_id}/priority/down")
async def priority_down(request: Request, torrent_id: int) -> dict[str, str]:
    cfg = request.app.state.cfg
    try:
        rpc = _get_rpc(cfg)
        await rpc.queue_move_down(torrent_id)
        return {"status": "moved_down", "id": str(torrent_id)}
    except Exception as e:
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
    )
    try:
        res = await enqueue_release(
            release,
            cfg,
            media_type=body.media_type,
            season=body.season,
            episode=body.episode,
            imdb_id=body.imdb_id,
            tmdb_id=body.tmdb_id,
        )
        return {"status": "queued", "result": str(res), "infohash": release.infohash}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to enqueue release: {e}") from e


class DownloadMagnetRequest(BaseModel):
    magnet: str


@router.post("/download/magnet")
async def download_magnet_api(request: Request, body: DownloadMagnetRequest) -> dict[str, Any]:
    cfg = request.app.state.cfg
    try:
        res = await download_magnet(body.magnet, cfg)
        return {"status": "queued", "result": str(res)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to ingest magnet: {e}") from e


@router.post("/import")
async def trigger_import(request: Request) -> dict[str, str]:
    cfg = request.app.state.cfg
    try:
        from arr.pipeline import _db, _poll_and_import, _sync_rpc_state

        db = _db(cfg)
        try:
            _sync_rpc_state(cfg, db)
            count = _poll_and_import(cfg, db)
            return {"status": "import_completed", "imported_count": str(count)}
        finally:
            db.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Import failed: {e}") from e
