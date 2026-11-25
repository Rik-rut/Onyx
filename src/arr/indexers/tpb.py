from __future__ import annotations

import logging
from pathlib import Path

from arr.core.models import MediaType, Query, Release
from arr.indexers.base import HttpClient, tracker_list
from arr.indexers.browser import BrowserSession, get_browser_session
from arr.indexers.tpb_parser import build_search_url, parse_page

logger = logging.getLogger(__name__)


class TpbAdapter:
    """The Pirate Bay indexer using a headless Playwright browser."""

    name = "tpb"

    def __init__(
        self,
        base_url: str,
        http: HttpClient,
        browser: BrowserSession | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http
        self._browser = browser or get_browser_session(cache_dir=cache_dir)

    def supports(self, media_type: MediaType) -> bool:
        return media_type in (MediaType.TV, MediaType.MOVIE)

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

        # Text-only search: the live 2026 endpoint cannot combine a
        # `category:` token with search text (verified 2026-11-23), so the
        # TV constraint is applied to the parsed rows instead (design D2).
        url = build_search_url(self.base_url, query, q.media_type)

        # Use browser to get JS-rendered page. A cold browser session can
        # render the row skeleton before the seed/leech spans load; retry
        # once so a partially rendered page does not zero every seeder and
        # empty the whole search.
        context = await self._browser.get_context()
        page = await context.new_page()
        html = None
        try:
            for attempt in (1, 2):
                resp = await page.goto(url, wait_until="networkidle", timeout=30000)
                if resp is None:
                    logger.warning("TPB navigation returned None for %s", url)
                    return []
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

        trackers = tracker_list(self.http.cfg)
        releases = parse_page(html, trackers=trackers, media_type=q.media_type)
        if q.media_type == MediaType.TV:
            # Client-side TV constraint: drop rows whose own category is a
            # movie category. Rows with an unrecognized category keep the
            # query's media type and remain.
            releases = [r for r in releases if r.media_type != MediaType.MOVIE]
        return releases[: q.limit]
