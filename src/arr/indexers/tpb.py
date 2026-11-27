from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from arr.core.models import MediaType, Query, Release
from arr.indexers.base import HttpClient, tracker_list
from arr.indexers.browser import BrowserSession, get_browser_session
from arr.indexers.tpb_parser import build_search_url, parse_apibay_json, parse_page

logger = logging.getLogger(__name__)


class TpbAdapter:
    """The Pirate Bay indexer (apibay JSON API with Playwright browser fallback)."""

    name = "tpb"

    def __init__(
        self,
        base_url: str,
        http: HttpClient,
        browser: BrowserSession | None = None,
        cache_dir: Path | None = None,
        api_base_url: str | None = None,
        api_get: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http
        self._browser = browser or get_browser_session(cache_dir=cache_dir)
        self._api_get = api_get
        if api_base_url is None:
            self.api_base_url = (
                "https://apibay.org"
                if self.base_url == "https://thepiratebay.org"
                else ""
            )
        else:
            self.api_base_url = api_base_url.rstrip("/")

    def supports(self, media_type: MediaType) -> bool:
        return media_type in (MediaType.TV, MediaType.MOVIE)

    async def _apibay_get(self, url: str, params: dict[str, str]) -> Any:
        """Fetch an apibay endpoint using Chrome TLS impersonation and HttpClient cache."""
        cache_key = url + json.dumps(params, sort_keys=True)
        cached = self.http.cache_get(cache_key, ttl_seconds=1800)
        if cached is not None:
            return json.loads(cached)

        await self.http._throttle("tpb")

        def _do_get():
            if self._api_get is not None:
                return self._api_get(url, params=params, timeout=5.0)
            from curl_cffi import requests

            return requests.get(
                url,
                params=params,
                impersonate="chrome",
                timeout=5.0,
            )

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = await asyncio.to_thread(_do_get)
                status = getattr(resp, "status_code", 0)
                if status in (429, 503):
                    await asyncio.sleep(min(2**attempt, 2))
                    continue
                if status != 200:
                    raise RuntimeError(f"apibay HTTP {status}")
                payload = resp.json()
                raw = getattr(resp, "content", None)
                if isinstance(raw, (bytes, bytearray)):
                    self.http.cache_put(cache_key, bytes(raw))
                return payload
            except Exception as exc:
                last_exc = exc
                if attempt + 1 < 3:
                    await asyncio.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f"GET {url} failed: {last_exc}")

    async def _search_api(
        self, query: str, media_type: MediaType, trackers: list[str]
    ) -> list[Release] | None:
        """Query apibay.org directly; return None when the API is unavailable."""
        if not self.api_base_url:
            return None
        url = f"{self.api_base_url}/q.php"
        # Unfiltered query works across TV (including season packs) and most movies;
        # some movie titles on apibay only populate under cat=200 (Video).
        param_sets: list[dict[str, str]] = [{"q": query}]
        if media_type == MediaType.MOVIE:
            param_sets.append({"q": query, "cat": "200"})
        for params in param_sets:
            try:
                payload = await self._apibay_get(url, params)
                releases = parse_apibay_json(payload, trackers=trackers, media_type=media_type)
                if releases or params is param_sets[-1]:
                    return releases
            except Exception as exc:
                logger.warning(
                    "apibay lookup failed for %s (%s); falling back to browser",
                    query,
                    exc,
                )
                return None
        return []

    async def _search_browser(
        self, query: str, media_type: MediaType, trackers: list[str]
    ) -> list[Release]:
        url = build_search_url(self.base_url, query, media_type)

        # Use browser to get JS-rendered page. A cold browser session can
        # render the row skeleton before the seed/leech spans load; retry
        # once so a partially rendered page does not zero every seeder and
        # empty the whole search.
        context = await self._browser.get_context()
        page = await context.new_page()
        html = None
        try:
            for attempt in (1, 2):
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                if resp is None:
                    logger.warning("TPB navigation returned None for %s", url)
                    return []
                try:
                    await page.wait_for_selector("li.list-entry span.item-seed", timeout=8000)
                except Exception:
                    pass
                html = await page.content()
                if html and "list-entry" in html and "item-seed" not in html:
                    logger.info(
                        "TPB page rendered without seed data (attempt %d)", attempt
                    )
                    continue
                break
        except Exception as exc:
            logger.warning("TPB browser error for %s: %s", url, exc)
            return []
        finally:
            await page.close()

        if not html or "list-entry" not in html:
            logger.info("TPB returned empty shell page for %s", query)
            return []

        return parse_page(html, trackers=trackers, media_type=media_type)

    async def search(self, q: Query) -> list[Release]:
        """Search TPB and return parsed Releases."""
        query = (q.text or q.title or "").strip()
        if not query:
            return []
        # Season/episode scoping (design D1): Sxx/Eyy tokens narrow the
        # indexer's own results. Anime releases number episodes across the
        # whole series, so the tokens are omitted there.
        if q.media_type == MediaType.TV and q.season is not None and not q.anime:
            token = f"S{q.season:02d}"
            if q.episode is not None:
                token += f"E{q.episode:02d}"
            query = f"{query} {token}"

        trackers = tracker_list(self.http.cfg)
        releases = await self._search_api(query, q.media_type, trackers)
        if releases is None:
            releases = await self._search_browser(query, q.media_type, trackers)

        if q.media_type == MediaType.TV:
            # Client-side TV constraint: drop rows whose own category is a
            # movie category. Rows with an unrecognized category keep the
            # query's media type and remain.
            releases = [r for r in releases if r.media_type != MediaType.MOVIE]
        return releases[: q.limit]
