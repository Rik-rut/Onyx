from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class BrowserSession:
    """Lazy per-process Playwright browser session for TPB scraping.

    Launches headless on first use, keeps a persistent user-data-dir
    under the cache directory, and prefers the requested browser channel
    (e.g. system Chrome) with bundled Chromium as the fallback.

    One instance per process is shared via :func:`get_browser_session`;
    the web app closes it in its lifespan hook (design D1).
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        channel: str = "chrome",
    ) -> None:
        self._cache_dir = cache_dir or Path(".cache") / "arr" / "pw" / "tpb"
        self._channel = channel
        self._browser = None  # type: ignore[assignment]
        self._context = None  # type: ignore[assignment]
        self._closed = False
        self._pw = None  # keep reference to Playwright context manager
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = asyncio.Lock()

    # -- public API --------------------------------------------------------

    async def get_context(self) -> object:
        """Return the browser context, lazy-initialising if needed."""
        if self._closed:
            raise RuntimeError("BrowserSession has been closed")
        async with self._lock:
            if self._context is not None:
                return self._context
            await self._launch()
            return self._context  # type: ignore[return-value]

    async def close(self) -> None:
        """Close the browser and release resources."""
        async with self._lock:
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception:  # pragma: no cover
                    pass
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:  # pragma: no cover
                    pass
            if self._pw is not None:
                try:
                    await self._pw.stop()
                except Exception:  # pragma: no cover
                    pass
            self._browser = None  # type: ignore[assignment]
            self._context = None  # type: ignore[assignment]
            self._pw = None
            self._closed = True

    # -- internal ----------------------------------------------------------

    async def _launch(self) -> None:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise ImportError(
                "playwright is required for TPB browser scraping. "
                "Install with: pip install playwright"
            ) from exc

        self._loop = asyncio.get_running_loop()
        user_data_dir = self._cache_dir
        user_data_dir.mkdir(parents=True, exist_ok=True)

        pw = async_playwright()
        self._pw = await pw.__aenter__()
        launch_args = {"args": ["--no-sandbox"]}
        # Prefer the requested channel (e.g. system Chrome); "chromium"
        # selects the bundled build straight away.
        channel = (
            self._channel if self._channel and self._channel != "chromium" else None
        )
        if channel:
            try:
                self._context = await self._pw.chromium.launch_persistent_context(
                    str(user_data_dir), channel=channel, **launch_args
                )
                return
            except Exception as exc:
                logger.warning(
                    "Browser channel %r unavailable (%s); falling back to bundled Chromium",
                    channel,
                    exc,
                )
        self._context = await self._pw.chromium.launch_persistent_context(
            str(user_data_dir), **launch_args
        )

    def __del__(self) -> None:
        """Best-effort close on GC.

        The primary close path is the web app's lifespan hook; this covers
        short-lived processes (CLI, tests) that never call close() explicitly.
        """
        if self._closed or (self._context is None and self._browser is None):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            if loop.is_running():
                loop.create_task(self.close())
            else:
                loop.run_until_complete(self.close())
        except Exception:  # pragma: no cover
            pass


_default_session: BrowserSession | None = None


def get_browser_session(
    cache_dir: Path | None = None,
    channel: str = "chrome",
) -> BrowserSession:
    """Return the process-wide BrowserSession singleton.

    One browser per process (design D1): repeated calls return the same
    session so TPB searches share a single persistent Chromium instance.
    """
    global _default_session
    if _default_session is None or _default_session._closed:
        _default_session = BrowserSession(cache_dir=cache_dir, channel=channel)
    return _default_session


async def close_browser_session() -> None:
    """Close the process-wide session if one was created (no-op otherwise)."""
    if _default_session is not None:
        await _default_session.close()
