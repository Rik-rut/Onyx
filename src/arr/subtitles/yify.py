from __future__ import annotations

import hashlib
import urllib.parse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from arr.subtitles.base import SubtitleCandidate, SubtitleError
from arr.subtitles.subscene import _extract_srt, _fetch_with, _guess_language


class YifySubtitlesClient:
    def __init__(self, base_url: str = "https://yifysubtitles.ch", session=None):
        self.base = base_url.rstrip("/")
        self._session = session

    def search(
        self,
        *,
        imdb_id: str | None = None,
        tmdb_id: int | None = None,
        title: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        languages: list[str] | None = None,
    ) -> list[SubtitleCandidate]:
        try:
            if imdb_id:
                url = f"{self.base}/movie-imdb/{imdb_id}"
            elif title:
                resp = _fetch_with(
                    self._session, f"{self.base}/search?q={urllib.parse.quote(title)}"
                )
                if getattr(resp, "status_code", 0) != 200:
                    raise SubtitleError(f"YIFY HTTP {getattr(resp, 'status_code', '?')}")
                tree = HTMLParser(resp.text)
                href = None
                for a in tree.css("a[href*='/movie-imdb/'], a[href*='/movie/']"):
                    href = a.attributes.get("href")
                    break
                if not href:
                    return []
                url = f"{self.base}{href}" if href.startswith("/") else href
            else:
                return []
            resp = _fetch_with(self._session, url)
        except SubtitleError:
            raise
        except Exception as e:
            raise SubtitleError(f"YIFY request failed: {e}") from e
        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"YIFY HTTP {getattr(resp, 'status_code', '?')}")
        tree = HTMLParser(resp.text)
        out: list[SubtitleCandidate] = []
        wanted = set(languages or ["en"])
        seen_links: set[str] = set()
        for li in tree.css("tr, li, .subtitle-row"):
            text = (li.text() or "").strip()
            if not text:
                continue
            d = li.css_first("a[href*='/subtitle/'], a[href*='download']")
            if not d:
                continue
            href = d.attributes.get("href") or ""
            link = href if href.startswith("http") else f"{self.base}{href}"
            if link in seen_links:
                continue
            seen_links.add(link)
            lang = _guess_language(text)
            if wanted and lang not in wanted:
                continue
            rid = int(hashlib.sha1(link.encode()).hexdigest()[:8], 16) % (10**8)
            out.append(
                SubtitleCandidate(
                    subtitle_id=rid,
                    file_id=rid,
                    language=lang,
                    release_name=text.split("\n")[0][:120],
                    downloads=0,
                    hearing_impaired="hi" in text.lower(),
                    hd=False,
                    upload_date="",
                    download_link=link,
                )
            )
        return out

    def download(self, candidate: SubtitleCandidate) -> bytes:
        if not candidate.download_link:
            raise SubtitleError("No download link")
        try:
            resp = _fetch_with(self._session, candidate.download_link)
        except Exception as e:
            raise SubtitleError(f"YIFY download failed: {e}") from e
        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"YIFY HTTP {getattr(resp, 'status_code', '?')}")
        return _extract_srt(resp.content)
