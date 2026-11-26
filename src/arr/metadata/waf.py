"""AWS WAF cookie provider for IMDb.

IMDb's HTML pages (charts, titles, search) sit behind an AWS WAF JavaScript
challenge: without a valid ``aws-waf-token`` cookie they answer HTTP 202 with
an interstitial that only a browser can solve. A headless Chromium solves the
challenge in a few seconds; the resulting cookies are then reused for plain
curl_cffi requests until they expire (kept on disk so server restarts do not
re-solve).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

__all__ = ["WafCookieProvider", "WafError"]

# Any IMDb page works to earn the token; a chart page doubles as a smoke test
# that the challenge page loads.
_CHALLENGE_URL = "https://www.imdb.com/chart/moviemeter/"
_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# AWS WAF tokens are short-lived; re-solve a bit before the edge does.
_TOKEN_TTL_SECONDS = 25 * 60


class WafError(Exception):
    """The WAF challenge could not be solved (browser missing or failed)."""


class WafCookieProvider:
    """Lazily acquire and cache the ``aws-waf-token`` cookie for imdb.com."""

    def __init__(self, cache_dir: Path | None = None, ttl: float = _TOKEN_TTL_SECONDS):
        self.cache_dir = Path(cache_dir) if cache_dir else Path(".cache") / "arr" / "waf"
        self.ttl = ttl
        self._cookies: dict[str, str] = {}
        self._fetched_at = 0.0

    @property
    def _path(self) -> Path:
        return self.cache_dir / "imdb_cookies.json"

    def cookies(self, force: bool = False) -> dict[str, str]:
        """Fresh token cookies; the browser only launches when nothing is fresh.

        Without ``force`` a stale/absent cache yields ``{}`` so callers can
        fall back to their normal degradation path instead of paying for a
        browser launch.
        """
        if not force and self._fresh(self._cookies, self._fetched_at):
            return self._cookies
        disk_cookies, disk_mtime = self._read_disk()
        if not force and self._fresh(disk_cookies, disk_mtime):
            self._cookies, self._fetched_at = disk_cookies, disk_mtime
            return self._cookies
        if not force:
            return {}
        try:
            solved = self._solve()
        except Exception as e:
            raise WafError(str(e)) from e
        self._cookies, self._fetched_at = solved, time.time()
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(solved), encoding="utf-8")
        except OSError:
            pass
        return solved

    def _fresh(self, cookies: dict[str, str], when: float) -> bool:
        return bool(cookies) and (time.time() - when) <= self.ttl

    def _read_disk(self) -> tuple[dict[str, str], float]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}, 0.0
        cookies = {
            str(k): str(v) for k, v in data.items() if isinstance(v, (str, int))
        }
        if "aws-waf-token" not in cookies:
            return {}, 0.0
        return cookies, self._path.stat().st_mtime

    def _solve(self) -> dict[str, str]:
        """Run the challenge in headless Chromium and return the cookies."""
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            try:
                ctx = browser.new_context(
                    user_agent=_CHROME_UA,
                    locale="en-US",
                    viewport={"width": 1366, "height": 900},
                )
                page = ctx.new_page()
                page.goto(
                    _CHALLENGE_URL, timeout=30_000, wait_until="domcontentloaded"
                )
                # The challenge sets the token cookie and reloads the page;
                # poll until the real page (with __NEXT_DATA__) has landed.
                for _ in range(20):
                    try:
                        if "__NEXT_DATA__" in page.content():
                            break
                    except Exception:
                        pass  # page is mid-reload
                    time.sleep(1)
                cookies = {c["name"]: c["value"] for c in ctx.cookies()}
            finally:
                browser.close()
        if "aws-waf-token" not in cookies:
            raise WafError("WAF challenge did not produce an aws-waf-token cookie")
        return cookies
