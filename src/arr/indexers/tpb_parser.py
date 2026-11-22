"""Parsers for The Pirate Bay search results pages.

TPB renders its search results with JavaScript, so the raw HTTP response is
an empty shell; the HTML parsed here is the fully rendered page captured by
:class:`arr.indexers.browser.BrowserSession` (design D6).

Live markup, verified 2026-11-23 against ``thepiratebay.org``:

* result rows are ``<li class="list-entry">`` items;
* the title anchor is unclassed, nested inside a ``span.item-name``;
* the category breadcrumb is a ``span.item-type`` whose **last** link is the
  leaf category (``TV-Shows`` / ``HD TV-Shows`` / ``UHD/4k TV-Shows`` /
  ``HD Movies`` / ``UHD/4k Movies``);
* the exact size in bytes is in a hidden ``input[name=size]``; the visible
  text uses binary units (``140.06 GiB``).

Current live category codes (from the page's own taxonomy links): 205
TV-Shows, 207 HD Movies, 208 HD TV-Shows, 211 UHD/4k Movies, 212 UHD/4k
TV-Shows. The old 501/502/504/506/507 scheme no longer exists. Note the
2026 endpoint does **not** combine a ``category:`` token with search text
(verified: such queries return no results), so TV searches constrain
results client-side by category text (design D2).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser

from arr.core.models import MediaType, Release
from arr.indexers.base import SchemaMismatchError

logger = logging.getLogger(__name__)

# Current live category codes (verified 2026-11-23). Documented for
# reference; see the module docstring for why they are not embedded in
# search URLs.
TV_CATEGORY_CODES = ["205", "208", "212"]
MOVIE_CATEGORY_CODES = ["200", "207", "211"]

_SIZE_RE = re.compile(r"([\d.]+)\s*(kib|kb|mib|mb|gib|gb|tib|tb|b)?", re.IGNORECASE)
_SIZE_UNITS = {
    "b": 1,
    "kb": 1024,
    "kib": 1024,
    "mb": 1024**2,
    "mib": 1024**2,
    "gb": 1024**3,
    "gib": 1024**3,
    "tb": 1024**4,
    "tib": 1024**4,
}


def build_search_url(
    base_url: str,
    query: str,
    media_type: MediaType,
    category_filter: str | None = None,
) -> str:
    """Build a TPB search URL for *query*.

    ``category_filter`` (a single live category code) is appended to the
    search terms. The 2026 endpoint ignores the search terms when a
    ``category:`` token is present (verified 2026-11-23), so callers pass
    it only for pure category-browse use and otherwise constrain results
    client-side (design D2).
    """
    parts = [query]
    if category_filter:
        parts.append(f"category:{category_filter}")
    encoded = "+".join(parts)
    return f"{base_url.rstrip('/')}/search.php?q={encoded}"


def parse_size(size_str: str | None) -> int:
    """Parse a human-readable size string to bytes.

    Supports decimal (KB/MB/GB/TB) and binary (KiB/MiB/GiB/TiB) units; a
    bare number is treated as bytes.
    """
    if not size_str:
        return 0
    match = _SIZE_RE.search(size_str)
    if not match:
        return 0
    value = float(match.group(1))
    unit = (match.group(2) or "b").lower()
    return int(value * _SIZE_UNITS.get(unit, 1))


def parse_int(value: str | None, default: int = 0) -> int:
    """Parse an integer from a string, returning default on failure."""
    if value is None:
        return default
    try:
        return int(value.strip())
    except (ValueError, TypeError):
        return default


def infer_media_type(category: str, fallback: MediaType) -> MediaType:
    """Map a row's item-type category text to a :class:`MediaType`.

    Unrecognized (or missing) category text yields *fallback* — pass the
    query's media type so TV searches don't mislabel unclassified rows.
    """
    text = (category or "").lower()
    if "tv" in text or "show" in text:
        return MediaType.TV
    if "movie" in text or "film" in text:
        return MediaType.MOVIE
    return fallback


def parse_row(
    node: object,
    trackers: list[str] | None = None,
    media_type: MediaType = MediaType.MOVIE,
) -> Release | None:
    """Parse a single ``li.list-entry`` node into a Release.

    *media_type* is the fallback for rows whose category text cannot be
    classified (see :func:`infer_media_type`).

    Returns ``None`` for malformed rows (logged as warning).
    Raises ``SchemaMismatchError`` when the page has rows but they are
    structurally broken (e.g. missing magnet URI).
    """
    try:
        # Live markup keeps the item-name class on the <span>; the anchor
        # is unclassed. The class-on-anchor shape (older pages) is the
        # fallback.
        title_node = (
            node.css_first("span.item-name a")
            or node.css_first("a.item-name")
            or node.css_first("a")
        )
        title = title_node.text().strip() if title_node is not None else ""
        if not title:
            raise SchemaMismatchError("tpb", "", "missing title in row")

        magnet_node = node.css_first('a[href^="magnet:"]')
        if magnet_node is None:
            # Fallback: look for any magnet link
            for a in node.css("a"):
                href = a.attributes.get("href", "")
                if href.startswith("magnet:"):
                    magnet_node = a
                    break
        magnet = magnet_node.attributes.get("href", "") if magnet_node is not None else ""
        if not magnet:
            raise SchemaMismatchError("tpb", "", "missing magnet URI in row")

        # Build magnet with trackers if not already present
        if trackers and "tracker" not in magnet.lower():
            tracker_str = "&".join(f"tr={t}" for t in trackers)
            separator = "&" if "?" in magnet else "?"
            magnet = f"{magnet}{separator}{tracker_str}"

        # The hidden input carries the exact byte count; the visible text
        # is a fallback only.
        size_bytes = 0
        size_input = node.css_first("input[name=size]")
        if size_input is not None:
            size_bytes = parse_int(size_input.attributes.get("value", ""))
        if size_bytes <= 0:
            size_node = node.css_first("span.item-size")
            if size_node is not None:
                size_bytes = parse_size(size_node.text())

        seed_node = node.css_first("span.item-seed")
        seeders = parse_int(seed_node.text() if seed_node is not None else None)

        leech_node = node.css_first("span.item-leech")
        leechers = parse_int(leech_node.text() if leech_node is not None else None)

        # Category: leaf of the item-type breadcrumb (live markup); older
        # pages carried the label on the anchor's title attribute.
        category = ""
        type_links = node.css("span.item-type a")
        if type_links:
            category = type_links[-1].text().strip()
        else:
            type_node = node.css_first("a[item-type]")
            if type_node is not None:
                category = (type_node.attributes.get("title", "") or type_node.text()).strip()

        return Release(
            indexer="tpb",
            title=title,
            infohash=_hash_from_magnet(magnet),
            magnet=magnet,
            media_type=infer_media_type(category, media_type),
            seeds=seeders,
            peers=leechers,
            size_bytes=size_bytes,
        )
    except SchemaMismatchError:
        raise
    except Exception as exc:
        logger.warning("Malformed TPB row: %s", exc)
        return None


def _hash_from_magnet(magnet: str) -> str:
    """Extract the infohash from a magnet URI."""
    marker = "btih:"
    idx = magnet.lower().find(marker)
    if idx >= 0:
        return magnet[idx + len(marker) :].split("&")[0].lower()
    return magnet[:40].lower()


def parse_page(
    html: str,
    trackers: list[str] | None = None,
    media_type: MediaType = MediaType.MOVIE,
) -> list[Release]:
    """Parse a rendered TPB search results page into a list of Releases.

    *media_type* is the fallback for rows whose category text cannot be
    classified; pass the query's media type.

    A page with zero ``li.list-entry`` rows returns an empty list
    (not an error). Malformed rows are logged and skipped.
    """
    tree = LexborHTMLParser(html)
    rows = tree.css("li.list-entry")

    if not rows:
        logger.info("TPB page has zero list-entry rows (empty result)")
        return []

    releases: list[Release] = []
    for row in rows:
        try:
            release = parse_row(row, trackers, media_type)
            if release is not None:
                releases.append(release)
        except SchemaMismatchError as exc:
            logger.warning("Skipping malformed TPB row: %s", exc)
        except Exception as exc:
            logger.warning("Skipping malformed TPB row: %s", exc)

    return releases


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
