from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from arr.log import get_logger
from arr.pipeline import _rpc
from arr.web.routes.auth import has_valid_session
from arr.web.routes.queue import fetch_merged_queue

logger = get_logger("ws")
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/queue")
async def websocket_queue(websocket: WebSocket) -> None:
    # Auth gate: reject an unauthenticated socket before accepting it so the
    # browser sees a refused handshake instead of an open, useless connection.
    if not has_valid_session(websocket.cookies):
        await websocket.close(code=4401)
        return
    await websocket.accept()
    client_ip = getattr(websocket.client, "host", "unknown") if websocket.client else "unknown"
    logger.info(f"WebSocket client connected to /ws/queue from {client_ip}")
    cfg = websocket.app.state.cfg

    try:
        while True:
            rpc_client = None
            try:
                rpc_client = _rpc(cfg)
            except Exception:
                rpc_client = None
            torrents_data = await fetch_merged_queue(cfg, rpc=rpc_client)

            payload = {
                "timestamp": time.time(),
                "torrents": torrents_data,
            }

            await websocket.send_json(payload)
            await asyncio.sleep(1.0)
    except (WebSocketDisconnect, asyncio.CancelledError):
        logger.info(f"WebSocket client disconnected from /ws/queue ({client_ip})")
