import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from arr.auth import AuthStore
from arr.config.settings import Config, default_config_path
from arr.log import get_logger
from arr.web.routes.auth import has_valid_session
from arr.web.routes.auth import router as auth_router
from arr.web.routes.config import router as config_router
from arr.web.routes.discover import router as discover_router
from arr.web.routes.library import router as library_router
from arr.web.routes.queue import router as queue_router
from arr.web.routes.search import router as search_router
from arr.web.routes.ws import router as ws_router

logger = get_logger("web")

STATIC_DIR = Path(__file__).parent / "static"
DIST_DIR = STATIC_DIR / "dist"


BUILD_HINT_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    "<title>Onyx frontend not built</title></head><body>"
    "<h1>Onyx frontend bundle is missing</h1>"
    "<p>No compiled SPA found at <code>src/arr/web/static/dist/index.html</code>. "
    "Build it from the repo root:</p>"
    "<pre>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</pre>"
    "<p>The REST API (<code>/api/*</code>) and the queue WebSocket "
    "(<code>/ws/queue</code>) work without the frontend bundle.</p>"
    "</body></html>"
)


def _spa_document() -> Response:
    """The compiled SPA entry HTML, or a build instruction when it is absent."""
    index_file = DIST_DIR / "index.html"
    if index_file.is_file():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content=BUILD_HINT_HTML)


def _dist_file(name: str) -> Path | None:
    """A static file inside dist/, refusing anything outside it."""
    candidate = (DIST_DIR / name).resolve()
    root = DIST_DIR.resolve()
    if candidate.is_file() and candidate.is_relative_to(root):
        return candidate
    return None


FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<text y=".9em" font-size="90">🎬</text>'
    "</svg>"
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = app.state.cfg
    stop_event = asyncio.Event()

    # Seed auth.toml when absent and warn while the default account stands.
    auth_store = app.state.auth
    auth_store.load()
    if auth_store.must_change_credentials:
        logger.warning(
            "Default web credentials admin / 1234 are in use - change them after the first login"
        )

    async def _startup_maintenance() -> None:
        """R2.3/R3.1: normalise downloads/ and index the disk library on startup."""
        try:
            from arr.pipeline import cleanup_duplicate_folders, sync_disk_library

            removed = await asyncio.to_thread(cleanup_duplicate_folders, cfg)
            if removed:
                logger.info(f"Startup cleanup removed {removed} duplicate folder(s)")
            stats = await asyncio.to_thread(sync_disk_library, cfg)
            logger.info(
                "Startup library scan: "
                f"{stats.get('movies', 0)} movie(s), {stats.get('shows', 0)} show(s), "
                f"{stats.get('episodes', 0)} episode(s), "
                f"{stats.get('monitored', 0)} auto-monitored"
            )
        except Exception as e:
            logger.warning(f"Startup library maintenance failed: {e}")

    await _startup_maintenance()

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
        # Release the shared TPB browser (design D1: one browser per
        # process, closed on shutdown).
        from arr.indexers.browser import close_browser_session

        await close_browser_session()


def create_app(cfg: Config, auth_path: Path | str | None = None) -> FastAPI:
    """Create and configure the FastAPI web application instance."""
    app = FastAPI(title="Onyx Web Dashboard", version="0.1.0", lifespan=lifespan)
    app.state.cfg = cfg
    app.state.auth = AuthStore(
        auth_path
        if auth_path is not None
        else (
            cfg.source_path.parent / "auth.toml"
            if cfg.source_path is not None
            else default_config_path().parent / "auth.toml"
        )
    )

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):
        """Gate every /api/* route except the login flow itself; the SPA
        document, static assets, and /favicon.ico stay open so the login
        page can render. The WebSocket is checked in its own handler."""
        path = request.url.path
        if path.startswith("/api/") and path not in ("/api/auth/login", "/api/auth/status"):
            if not has_valid_session(request.cookies):
                return JSONResponse({"detail": "authentication required"}, status_code=401)
        return await call_next(request)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000
        path = request.url.path
        if request.url.query:
            path += f"?{request.url.query}"
        # Skip noisy static assets from cluttering the log
        if not path.startswith(("/static", "/assets")):
            logger.info(f"{request.method} {path} -> {response.status_code} ({duration_ms:.1f}ms)")
        return response

    app.include_router(auth_router)
    app.include_router(search_router)
    app.include_router(discover_router)
    app.include_router(queue_router)
    app.include_router(library_router)
    app.include_router(config_router)
    app.include_router(ws_router)

    assets_dir = DIST_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/favicon.ico")
    async def get_favicon() -> Response:
        return Response(content=FAVICON_SVG, media_type="image/svg+xml")

    @app.get("/", response_class=HTMLResponse)
    async def get_index() -> Response:
        return _spa_document()

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> Response:
        """Client-side routes reload to the SPA entry document; unknown /api
        and /ws paths stay 404 JSON so they never masquerade as HTML."""
        if full_path.startswith(("api/", "ws/")):
            raise HTTPException(status_code=404)
        static_file = _dist_file(full_path)
        if static_file is not None:
            return FileResponse(static_file)
        return _spa_document()

    return app
