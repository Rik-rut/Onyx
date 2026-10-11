import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from arr.config.settings import Config
from arr.log import get_logger
from arr.web.routes.config import router as config_router
from arr.web.routes.library import router as library_router
from arr.web.routes.queue import router as queue_router
from arr.web.routes.search import router as search_router
from arr.web.routes.ws import router as ws_router

logger = get_logger("web")

FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<text y=".9em" font-size="90">🎬</text>'
    "</svg>"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = app.state.cfg
    stop_event = asyncio.Event()

    async def _poller() -> None:
        await asyncio.sleep(1.0)
        while not stop_event.is_set():
            try:
                from arr.pipeline import (
                    _apply_seeding_policy,
                    _db,
                    _poll_and_import,
                    _promote_queued,
                    _sync_rpc_state,
                )

                def _run_sync_tasks() -> None:
                    db = _db(cfg)
                    try:
                        _sync_rpc_state(cfg, db)
                        _poll_and_import(cfg, db)
                        _apply_seeding_policy(cfg, db)
                    finally:
                        db.close()

                await asyncio.to_thread(_run_sync_tasks)
                db = _db(cfg)
                try:
                    await _promote_queued(cfg, db)
                finally:
                    db.close()
            except Exception as e:
                logger.debug(f"Background poller tick error: {e}")

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            except TimeoutError:
                pass

    poller_task = asyncio.create_task(_poller())
    try:
        yield
    finally:
        stop_event.set()
        poller_task.cancel()
        try:
            await poller_task
        except (asyncio.CancelledError, Exception):
            pass


def create_app(cfg: Config) -> FastAPI:
    """Create and configure the FastAPI web application instance."""
    app = FastAPI(title="ARR Web Dashboard", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        path = request.url.path
        if request.url.query:
            path += f"?{request.url.query}"
        # Skip noisy static assets from cluttering the log
        if not path.startswith("/static"):
            logger.info(f"{request.method} {path} -> {response.status_code} ({duration_ms:.1f}ms)")
        return response

    app.include_router(search_router)
    app.include_router(queue_router)
    app.include_router(library_router)
    app.include_router(config_router)
    app.include_router(ws_router)

    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "index.html"

    @app.get("/favicon.ico")
    async def get_favicon() -> Response:
        return Response(content=FAVICON_SVG, media_type="image/svg+xml")

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> HTMLResponse:
        content = index_file.read_text(encoding="utf-8")
        return HTMLResponse(content=content)

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app
