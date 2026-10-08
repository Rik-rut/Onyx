from __future__ import annotations

import hashlib
import io
import re
import urllib.parse
import zipfile

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from arr.subtitles.base import SubtitleCandidate, SubtitleError


def _fetch_with(session, url: str, timeout: int = 20):
    if session is not None:
        return session.get(url, timeout=timeout)
    from curl_cffi import requests

    return requests.get(url, impersonate="chrome", timeout=timeout)


class SubsceneClient:
    def __init__(self, base_url: str = "https://subscene.com", session=None):
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
        query = title or imdb_id or ""
        if not query:
            return []
        if season is not None and episode is not None:
            query = f"{query} S{season:02d}E{episode:02d}"
        try:
            resp = _fetch_with(
                self._session,
                f"{self.base}/subtitles/searchbytitle?query={urllib.parse.quote(query)}",
            )
        except Exception as e:
            raise SubtitleError(f"Subscene request failed: {e}") from e
        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"Subscene HTTP {getattr(resp, 'status_code', '?')}")
        tree = HTMLParser(resp.text)
        title_href = None
        for a in tree.css("a[href*='/subtitles/']"):
            href = a.attributes.get("href") or ""
            if "/subtitles/" in href and "searchbytitle" not in href:
                title_href = href
                break
        if not title_href:
            return []
        try:
            resp2 = _fetch_with(self._session, f"{self.base}{title_href}")
        except Exception as e:
            raise SubtitleError(f"Subscene request failed: {e}") from e
        if getattr(resp2, "status_code", 0) != 200:
            raise SubtitleError(f"Subscene HTTP {getattr(resp2, 'status_code', '?')}")
        tree2 = HTMLParser(resp2.text)
        out: list[SubtitleCandidate] = []
        wanted = set(languages or ["en"])
        for li in tree2.css("li"):
            text = li.text() or ""
            node = li.css_first("a[href*='/subtitle/']")
            if not node:
                continue
            href = node.attributes.get("href") or ""
            link = href if href.startswith("http") else f"{self.base}{href}"
            lang = _guess_language(text)
            if wanted and lang not in wanted:
                continue
            hi = "hearing impaired" in text.lower() or "hi)" in text.lower()
            rid = int(hashlib.sha1(link.encode()).hexdigest()[:8], 16) % (10**8)
            out.append(
                SubtitleCandidate(
                    subtitle_id=rid,
                    file_id=rid,
                    language=lang,
                    release_name=(node.text() or "").strip(),
                    downloads=0,
                    hearing_impaired=hi,
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
            raise SubtitleError(f"Subscene download failed: {e}") from e
        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"Subscene HTTP {getattr(resp, 'status_code', '?')}")
        return _extract_srt(resp.content)


def _guess_language(text: str) -> str:
    low = text.lower()
    if "english" in low:
        return "en"
    m = re.search(
        r"\b(spanish|french|german|italian|portuguese|dutch|polish|russian|arabic|"
        r"korean|chinese|japanese)\b",
        low,
    )
    if m:
        return {
            "spanish": "es", "french": "fr", "german": "de", "italian": "it",
            "portuguese": "pt", "dutch": "nl", "polish": "pl", "russian": "ru",
            "arabic": "ar", "korean": "ko", "chinese": "zh", "japanese": "ja",
        }[m.group(1)]
    return "en"


def _extract_srt(content: bytes) -> bytes:
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            names = [
                n
                for n in z.namelist()
                if n.lower().endswith((".srt", ".ass", ".sub", ".vtt"))
            ]
            if not names:
                raise SubtitleError("No subtitle file in archive")
            return z.read(names[0])
    return content
