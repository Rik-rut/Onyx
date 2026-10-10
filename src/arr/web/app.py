from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from arr.config.settings import Config
from arr.web.routes.config import router as config_router
from arr.web.routes.library import router as library_router
from arr.web.routes.queue import router as queue_router
from arr.web.routes.search import router as search_router
from arr.web.routes.ws import router as ws_router


def create_app(cfg: Config) -> FastAPI:
    """Create and configure the FastAPI web application instance."""
    app = FastAPI(title="ARR Web Dashboard", version="0.1.0")
    app.state.cfg = cfg

    app.include_router(search_router)
    app.include_router(queue_router)
    app.include_router(library_router)
    app.include_router(config_router)
    app.include_router(ws_router)

    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "index.html"

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> HTMLResponse:
        content = index_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
