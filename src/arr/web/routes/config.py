from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from arr.config.settings import save_config
from arr.log import get_logger

logger = get_logger("config")
router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("")
async def get_config(request: Request) -> dict[str, Any]:
    cfg = request.app.state.cfg
    return cfg.redacted()


class UpdateConfigRequest(BaseModel):
    download_root: str | None = None
    library_root: str | None = None
    import_mode: str | None = None
    max_concurrent_downloads: int | None = None
    prefer_season_packs: bool | None = None
    seeding_policy: str | None = None
    resolutions: list[str] | None = None
    subtitle_languages: list[str] | None = None
    subtitles_enabled: bool | None = None
    subtitles_forced_only: bool | None = None
    max_download_speed_kbps: int | None = None
    max_upload_speed_kbps: int | None = None


@router.put("")
async def update_config(request: Request, body: UpdateConfigRequest) -> dict[str, Any]:
    cfg = request.app.state.cfg

    updates = body.model_dump(exclude_unset=True)
    if "import_mode" in updates and updates["import_mode"] not in ("hardlink", "copy", "move"):
        raise HTTPException(status_code=400, detail="Invalid import_mode")

    if "seeding_policy" in updates and updates["seeding_policy"] not in (
        "ratio",
        "time",
        "manual",
        "remove_on_import",
    ):
        raise HTTPException(status_code=400, detail="Invalid seeding_policy")

    for k, v in updates.items():
        if v is not None:
            cfg.values[k] = v

    try:
        await asyncio.to_thread(save_config, cfg)
        logger.info(f"Updated configuration keys: {list(updates.keys())}")
        return {"status": "saved", "config": cfg.redacted()}
    except Exception as e:
        logger.error(f"Failed to save configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save config: {e}") from e
