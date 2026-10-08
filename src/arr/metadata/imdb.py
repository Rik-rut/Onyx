from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

from selectolax.lexbor import LexborHTMLParser as HTMLParser


class ImdbError(Exception):
    pass


_TITLE_RE = re.compile(r"/title/(tt\d+)/")


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def degrade(query: str) -> None:
    print(
        f"warning: IMDb scraping failed; falling back to free-text search for {query!r}",
        file=sys.stderr,
    )


class ImdbClient:
    def __init__(self, cfg, cache_dir: Path | None = None, session=None):
        self.cfg = cfg
        self.base = str(cfg.get("imdb_base_url", "https://www.imdb.com")).rstrip("/")
        self.suggestion = str(
            cfg.get("imdb_suggestion_base_url", "https://v3.sg.media-imdb.com/suggestion")
        ).rstrip("/")
        self.cache_dir = cache_dir or Path.home() / ".cache" / "arr" / "imdb"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._session = session

    def _fetch(self, url: str) -> str:
        try:
            if self._session is not None:
                resp = self._session.get(url, timeout=20)
            else:
                from curl_cffi import requests

                resp = requests.get(url, impersonate="chrome", timeout=20)
        except Exception as e:
            raise ImdbError(f"IMDb request failed: {e}") from e
        if getattr(resp, "status_code", 0) != 200:
            raise ImdbError(f"IMDb HTTP {getattr(resp, 'status_code', '?')}")
        return resp.text

    def _cache_path(self, key: str) -> Path:
        h = hashlib.sha256(key.encode()).hexdigest()[:24]
        return self.cache_dir / f"{h}.html"

    def _cached_get(self, key: str, url: str) -> str:
        ttl = float(self.cfg.get("cache_ttl_hours", 24)) * 3600
        cp = self._cache_path(key)
        if cp.exists() and (time.time() - cp.stat().st_mtime) <= ttl:
            return cp.read_text(encoding="utf-8", errors="replace")
        try:
            html = self._fetch(url)
        except ImdbError:
            if cp.exists():
                return cp.read_text(encoding="utf-8", errors="replace")
            raise
        try:
            cp.write_text(html, encoding="utf-8")
        except OSError:
            pass
        return html

    def search_movie(self, query: str) -> dict | None:
        try:
            html = self._cached_get(f"search:{query}", f"{self.base}/find/?q={query}")
            found = self._parse_search_results(html)
            if found:
                return found
        except ImdbError:
            pass
        return self._search_suggestion(query)

    @staticmethod
    def _parse_search_results(html: str) -> dict | None:
        tree = HTMLParser(html)
        seen: set[str] = set()
        for a in tree.css("a[href*='/title/tt']"):
            href = a.attributes.get("href") or ""
            m = _TITLE_RE.search(href)
            if not m or m.group(1) in seen:
                continue
            title = (a.text() or "").strip()
            if not title:
                continue
            seen.add(m.group(1))
            return {"id": m.group(1), "title": title, "imdb_id": m.group(1), "year": _year_near(a)}
        return None

    def _search_suggestion(self, query: str) -> dict | None:
        url = f"{self.suggestion}/x/{urllib.parse.quote(query)}.json"
        try:
            text = self._cached_get(f"suggestion:{query}", url)
        except ImdbError:
            return None
        try:
            data = json.loads(text)
        except ValueError:
            return None
        for item in data.get("d", []) or []:
            tid = str(item.get("id") or "")
            title = (item.get("l") or "").strip()
            if not tid.startswith("tt") or not title:
                continue
            return {"id": tid, "title": title, "imdb_id": tid, "year": item.get("y")}
        return None

    def movie_details(self, imdb_id: str) -> dict:
        html = self._cached_get(f"title:{imdb_id}", f"{self.base}/title/{imdb_id}/")
        tree = HTMLParser(html)
        title_tag = tree.css_first("h1") or tree.css_first("title")
        title = (title_tag.text() or "").strip() if title_tag else ""
        year = None
        meta = tree.css_first("meta[property='og:title']")
        if meta:
            m = re.search(r"\((\d{4})\)", meta.attributes.get("content", "") or "")
            if m:
                year = int(m.group(1))
        return {"id": imdb_id, "title": title, "imdb_id": imdb_id, "year": year}


def _year_near(node) -> int | None:
    parent = node.parent
    if parent is None:
        return None
    m = re.search(r"\b(19|20)\d{2}\b", parent.text() or "")
    return int(m.group(0)) if m else None
