"""Parser for Anime Tosho (animetosho.net) search results pages.

The search page (``GET /search?q=<title>``) is server-rendered HTML, so the
raw HTTP response is parsed directly (no browser session needed).

Live markup, verified 2026-11-26 against ``animetosho.net``:

* result rows are ``<div class="home_list_entry">`` blocks (some carry an
  extra ``home_list_entry_alt`` class);
* the exact size in bytes is in the ``div.size`` title attribute
  (``Total file size: 1527565407 bytes``);
* the release title is in the ``div.link`` anchor's ``title`` attribute;
* the magnet URI is in the ``Magnet`` anchor's ``href`` (HTML-escaped
  ``&amp;`` separators);
* seeders/leechers are in the ``span.swarm`` title attribute
  (``Seeders: 216 / Leechers: 91``).

DDL-only rows (no Magnet anchor) are valid rows that the parser skips.
"""

from __future__ import annotations

import html
import logging
import re
from pathlib import Path

from arr.indexers.base import SchemaMismatchError

logger = logging.getLogger(__name__)

_ROW_MARKER = '<div class="home_list_entry'
_SIZE_RE = re.compile(r'<div class="size" title="Total file size: (\d+) bytes"')
_TITLE_RE = re.compile(r'<div class="link"><a href="/view/[^"]*" title="([^"]*)"')
_MAGNET_RE = re.compile(r'<a href="(magnet:[^"]*)"[^>]*>Magnet</a>')
_SWARM_RE = re.compile(r'<span title="Seeders: (\d+) / Leechers: (\d+)" class="swarm"')


def parse_rows(page: str) -> list[dict]:
    """Parse a rendered search page into row dicts.

    Returns one dict per ``home_list_entry`` row that has a magnet link:
    ``{"title", "magnet", "size_bytes", "seeders", "leechers"}``. Rows
    without a magnet (DDL-only) are skipped, as are rows without a title.

    A page with zero rows is a valid empty result. A page with no
    recognizable search layout (no rows and no search form markers) raises
    :class:`SchemaMismatchError`.
    """
    if _ROW_MARKER not in page:
        if "search_box" not in page and "Search Results" not in page:
            raise SchemaMismatchError(
                "animetosho", "search page", "no search layout markers found"
            )
        logger.info("animetosho page has zero home_list_entry rows (empty result)")
        return []
    rows: list[dict] = []
    for chunk in page.split(_ROW_MARKER)[1:]:
        try:
            row = _parse_row(chunk)
        except Exception as exc:
            logger.warning("Skipping malformed animetosho row: %s", exc)
            continue
        if row is not None:
            rows.append(row)
    return rows


def _parse_row(chunk: str) -> dict | None:
    """Parse one ``home_list_entry`` block into a row dict (or None)."""
    magnet_m = _MAGNET_RE.search(chunk)
    if magnet_m is None:
        return None
    title_m = _TITLE_RE.search(chunk)
    title = html.unescape(title_m.group(1)) if title_m else ""
    if not title:
        return None
    size_m = _SIZE_RE.search(chunk)
    swarm_m = _SWARM_RE.search(chunk)
    return {
        "title": title,
        "magnet": html.unescape(magnet_m.group(1)),
        "size_bytes": int(size_m.group(1)) if size_m else 0,
        "seeders": int(swarm_m.group(1)) if swarm_m else 0,
        "leechers": int(swarm_m.group(2)) if swarm_m else 0,
    }


def load_fixture(name: str) -> str:
    """Load a test fixture HTML file from the tests directory."""
    fixture_path = Path(__file__).parent.parent.parent.parent / "tests" / "fixtures" / name
    if fixture_path.exists():
        return fixture_path.read_text(encoding="utf-8")
    # Fallback: look relative to cwd
    fallback = Path("tests/fixtures") / name
    if fallback.exists():
        return fallback.read_text(encoding="utf-8")
    return ""
