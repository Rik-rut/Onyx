from __future__ import annotations

import hashlib
import urllib.parse

from arr.subtitles.base import SubtitleCandidate, SubtitleError
from arr.subtitles.subscene import _extract_srt, _fetch_with, _guess_language


class SubdlClient:
    """Client for querying SubDL API for movie and TV subtitles."""

    def __init__(
        self,
        base_url: str = "https://api.subdl.com",
        api_key: str = "",
        session=None,
    ):
        self.base = base_url.rstrip("/")
        self.api_key = api_key
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
        if not self.api_key:
            return []
        query = title or imdb_id or ""
        if not query:
            return []

        wanted_langs = languages or ["en"]
        params = {
            "api_key": self.api_key,
            "film_name": query,
            "type": "tv" if (season is not None and episode is not None) else "movie",
            "languages": ",".join(wanted_langs),
        }
        if season is not None:
            params["season_number"] = str(season)
        if episode is not None:
            params["episode_number"] = str(episode)

        url = f"{self.base}/api/v1/subtitles?{urllib.parse.urlencode(params)}"
        try:
            resp = _fetch_with(self._session, url)
        except Exception as e:
            raise SubtitleError(f"SubDL request failed: {e}") from e

        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"SubDL HTTP {getattr(resp, 'status_code', '?')}")

        try:
            data = resp.json()
        except Exception as e:
            raise SubtitleError(f"SubDL invalid JSON response: {e}") from e

        if not data.get("status"):
            return []

        out: list[SubtitleCandidate] = []
        for item in data.get("subtitles", []):
            rel_name = item.get("release_name") or item.get("name") or query
            lang_str = item.get("lang") or item.get("language") or "en"
            lang = _guess_language(lang_str)
            sub_url = item.get("url") or ""
            if not sub_url:
                continue
            if not sub_url.startswith("http"):
                sub_url = f"https://dl.subdl.com{sub_url}"
            rid = int(hashlib.sha1(sub_url.encode()).hexdigest()[:8], 16) % (10**8)
            hi = bool(item.get("hi", False))
            out.append(
                SubtitleCandidate(
                    subtitle_id=rid,
                    file_id=rid,
                    language=lang,
                    release_name=rel_name,
                    downloads=item.get("download_count", 0),
                    hearing_impaired=hi,
                    hd=True,
                    upload_date="",
                    download_link=sub_url,
                )
            )
        return out

    def download(self, candidate: SubtitleCandidate) -> bytes:
        if not candidate.download_link:
            raise SubtitleError("No download link")
        try:
            resp = _fetch_with(self._session, candidate.download_link)
        except Exception as e:
            raise SubtitleError(f"SubDL download failed: {e}") from e

        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"SubDL HTTP {getattr(resp, 'status_code', '?')}")

        return _extract_srt(resp.content)
