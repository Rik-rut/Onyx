from __future__ import annotations

import hashlib
import io
import re
import urllib.parse
import zipfile

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from arr.subtitles.base import SubtitleCandidate, SubtitleError


def _fetch_with(session, url: str, timeout: int = 20, headers: dict | None = None):
    kwargs: dict = {"timeout": timeout}
    if headers:
        kwargs["headers"] = headers
    if session is not None:
        return session.get(url, **kwargs)
    from curl_cffi import requests

    return requests.get(url, impersonate="chrome", **kwargs)


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
        content = resp.content
        trimmed = content.lstrip()
        if (
            trimmed.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"<head", b"<HEAD"))
            or b"<html" in trimmed[:300].lower()
        ):
            # Intermediate details page: follow download button
            tree = HTMLParser(resp.text)
            btn = tree.css_first(
                "a#downloadButton, a[href*='/subtitles/download/'], a[href*='/download']"
            )
            if btn and btn.attributes.get("href"):
                href = btn.attributes.get("href") or ""
                url = href if href.startswith("http") else f"{self.base}{href}"
                try:
                    resp2 = _fetch_with(self._session, url)
                except Exception as e:
                    raise SubtitleError(f"Subscene download failed: {e}") from e
                if getattr(resp2, "status_code", 0) != 200:
                    raise SubtitleError(f"Subscene HTTP {getattr(resp2, 'status_code', '?')}")
                content = resp2.content
        return _extract_srt(content)


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


def is_valid_subtitle_payload(data: bytes) -> bool:
    if not data:
        return False
    trimmed = data.lstrip()
    if (
        trimmed.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"<head", b"<HEAD"))
        or b"<html" in trimmed[:300].lower()
    ):
        return False
    if b"-->" in data:
        return True
    if trimmed.startswith(b"WEBVTT"):
        return True
    if b"[Script Info]" in data or b"Dialogue:" in data:
        return True
    if re.match(rb"^\s*1\s*[\r\n]", data):
        return True
    if re.match(rb"^\{[0-9]+\}\{[0-9]+\}", trimmed):
        return True
    return False


def _normalize_to_utf8(data: bytes) -> bytes:
    """Normalize subtitle text bytes to UTF-8 without BOM."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "iso-8859-1"):
        try:
            return data.decode(enc).encode("utf-8")
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace").encode("utf-8")


def _extract_srt(content: bytes) -> bytes:
    if not content:
        raise SubtitleError("Empty subtitle content")
    if content[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as z:
                names = [
                    n
                    for n in z.namelist()
                    if n.lower().endswith((".srt", ".ass", ".sub", ".vtt"))
                ]
                if not names:
                    raise SubtitleError("No subtitle file in archive")
                extracted = z.read(names[0])
        except zipfile.BadZipFile as e:
            raise SubtitleError(f"Corrupt subtitle ZIP archive: {e}") from e
        if not is_valid_subtitle_payload(extracted):
            raise SubtitleError("Invalid subtitle payload in archive")
        return _normalize_to_utf8(extracted)

    trimmed = content.lstrip()
    if (
        trimmed.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML", b"<head", b"<HEAD"))
        or b"<html" in trimmed[:300].lower()
    ):
        raise SubtitleError(
            "Invalid subtitle payload: received HTML instead of subtitle/ZIP archive"
        )
    if not is_valid_subtitle_payload(content):
        raise SubtitleError("Invalid subtitle payload: not a valid subtitle or ZIP archive")
    return _normalize_to_utf8(content)
