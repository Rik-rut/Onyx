"""Keyless movie-metadata enrichment from Wikipedia + Wikidata.

Used by the IMDb client's degraded path, which is what runs when IMDb title
pages are unreachable (this network gets an AWS WAF challenge instead of the
title page, so synopsis/genres/runtime never arrive). Wikipedia's article
intro supplies the synopsis, Wikidata's genre property supplies the genres,
and the article infobox supplies the runtime — no API key, no new dependency.

Every lookup is best-effort: unresolved pieces come back empty and nothing
here raises, so a movie page degrades to exactly the payload it had before.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

WIKI_API = "https://en.wikipedia.org/w/api.php"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
USER_AGENT = "OnyxMedia/0.1 (+https://localhost)"
_CACHE_DIR = Path(".cache") / "arr" / "wiki"
_OVERVIEW_LIMIT = 1600
_RUNTIME_RE = re.compile(r"\|\s*runtime\s*=\s*(\d+)\s*minutes?", re.I)

# An IMDb title can resolve to a person/album/game article ("Oppenheimer"
# lands on the physicist), so only articles whose lead paragraph says the
# subject is a film/movie are accepted as a movie synopsis source.
_FILM_HEAD = 300


def _dig(obj: Any, *keys: str) -> Any:
    """Walk a dict path without raising on missing or unexpected shapes."""
    for key in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _get(url: str, params: dict[str, Any] | None = None) -> dict:
    """One MediaWiki API call; an empty dict on any transport or JSON failure."""
    try:
        resp = httpx.get(
            url,
            params=params or {},
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            follow_redirects=True,
        )
        if resp.status_code != 200:
            return {}
        data = resp.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _is_film(extract: str) -> bool:
    head = extract[:_FILM_HEAD].lower()
    return "film" in head or "movie" in head


def _page(title: str) -> tuple[str, str | None, str] | None:
    """Exact-title lookup: (page title, Wikidata Q-id, intro extract) or None."""
    data = _get(
        WIKI_API,
        {
            "action": "query",
            "titles": title,
            "prop": "pageprops|extracts",
            "redirects": 1,
            "exintro": 1,
            "explaintext": 1,
            "format": "json",
            "formatversion": 2,
        },
    )
    pages = _dig(data, "query", "pages") or []
    page = pages[0] if pages and isinstance(pages[0], dict) else {}
    if not page or "missing" in page:
        return None
    extract = str(page.get("extract") or "")
    props = page.get("pageprops") if isinstance(page.get("pageprops"), dict) else {}
    qid = props.get("wikibase_item")
    return (str(page.get("title") or ""), str(qid) if qid else None, extract)


def _resolve(title: str, year: int | None) -> tuple[str, str | None, str] | None:
    """The film article for a title: exact match first, then a search fallback.

    The fallback query carries the release year and the word "film" because
    bare titles are ambiguous (person/album/game pages share them).
    """
    page = _page(title)
    if page and _is_film(page[2]):
        return page
    search = _get(
        WIKI_API,
        {
            "action": "query",
            "list": "search",
            "srsearch": f"{title} ({year}) film" if year else f"{title} film",
            "srlimit": 5,
            "namespace": 0,
            "format": "json",
            "formatversion": 2,
        },
    )
    for hit in (_dig(search, "query", "search") or [])[:5]:
        candidate_title = str(_dig(hit, "title") or "")
        if not candidate_title:
            continue
        candidate = _page(candidate_title)
        if candidate and _is_film(candidate[2]):
            return candidate
    return None


def _genres(qid: str | None) -> list[str]:
    """Genre labels from Wikidata property P136 (genre of a creative work)."""
    if not qid:
        return []
    entity = _dig(
        _get(f"{WIKIDATA_ENTITY}/{qid}.json"), "entities", qid, "claims", "P136"
    )
    ids: list[str] = []
    for claim in (entity or []):
        value = _dig(claim, "mainsnak", "datavalue", "value")
        if isinstance(value, dict):
            item = str(value.get("id") or "")
            if item:
                ids.append(item)
    if not ids:
        return []
    labels = _get(
        WIKIDATA_API,
        {
            "action": "wbgetentities",
            "ids": "|".join(ids),
            "props": "labels",
            "languages": "en",
            "format": "json",
            "formatversion": 2,
        },
    )
    out: list[str] = []
    for item in ids:
        label = str(_dig(labels, "entities", item, "labels", "en", "value") or "").strip()
        # Wikidata labels are item names ("Science fiction film"); the IMDb
        # genre row wants the genre itself.
        clean = re.sub(r"\s+film$", "", label, flags=re.I).strip()
        if clean and clean not in out:
            out.append(clean)
        if len(out) >= 4:
            break
    return out


def _runtime(page_title: str) -> int | None:
    """Runtime in minutes from the article's infobox wikitext, if declared."""
    data = _get(
        WIKI_API,
        {
            "action": "parse",
            "page": page_title,
            "prop": "wikitext",
            "section": 0,
            "format": "json",
            "formatversion": 2,
        },
    )
    wikitext = str(_dig(data, "parse", "wikitext") or "")
    match = _RUNTIME_RE.search(wikitext)
    return int(match.group(1)) if match else None


def _cache_path(title: str, year: int | None) -> Path:
    key = hashlib.sha256(f"wiki|{title}|{year}".encode()).hexdigest()[:24]
    return _CACHE_DIR / f"{key}.json"


def _read_cache(title: str, year: int | None, cfg: Any) -> dict | None:
    try:
        path = _cache_path(title, year)
        ttl = int(cfg.get("cache_ttl_hours", 24)) * 3600
        if not path.exists() or (time.time() - path.stat().st_mtime) > ttl:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {
        "overview": str(data.get("overview") or ""),
        "genres": [str(g) for g in (data.get("genres") or []) if str(g)],
        "runtime": data.get("runtime"),
    }


def _write_cache(title: str, year: int | None, result: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(title, year).write_text(
            json.dumps(result, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass  # an unwritable cache must not cost the user their data


def _trim(text: str) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= _OVERVIEW_LIMIT:
        return text
    cut = text[:_OVERVIEW_LIMIT]
    boundary = cut.rfind(" ")
    return (cut[:boundary] if boundary > 0 else cut).rstrip()


def enrich_movie(cfg: Any, title: str, year: int | None = None) -> dict:
    """Return {"overview": str, "genres": list[str], "runtime": int | None}.

    Never raises; unresolved pieces are empty.
    """
    title = str(title or "").strip()
    if not title:
        return {"overview": "", "genres": [], "runtime": None}
    cached = _read_cache(title, year, cfg)
    if cached is not None:
        return cached

    result: dict[str, Any] = {"overview": "", "genres": [], "runtime": None}
    try:
        resolved = _resolve(title, year)
        if not resolved:
            return result
        page_title, qid, extract = resolved
        result["overview"] = _trim(extract)
        # Genres and runtime are independent lookups on the resolved page.
        with ThreadPoolExecutor(max_workers=2) as pool:
            genres_job = pool.submit(_genres, qid)
            runtime_job = pool.submit(_runtime, page_title)
            result["genres"] = genres_job.result()
            result["runtime"] = runtime_job.result()
    except Exception:
        pass  # best-effort: keep whatever was accumulated
    if result["overview"] or result["genres"] or result["runtime"]:
        _write_cache(title, year, result)
    return result
