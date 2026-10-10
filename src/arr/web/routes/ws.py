from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from arr.pipeline import _rpc
from arr.web.routes.queue import STATUS_NAMES

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/queue")
async def websocket_queue(websocket: WebSocket) -> None:
    await websocket.accept()
    cfg = websocket.app.state.cfg

    try:
        while True:
            torrents_data: list[dict[str, Any]] = []
            try:
                rpc = _rpc(cfg)
                torrents = await rpc.list_torrents()
                for t in torrents:
                    p_done = float(t.get("percentDone") or 0.0)
                    status_val = int(t.get("status") or 0)
                    torrents_data.append(
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
            except Exception:
                torrents_data = []

            payload = {
                "timestamp": time.time(),
                "torrents": torrents_data,
            }

            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
