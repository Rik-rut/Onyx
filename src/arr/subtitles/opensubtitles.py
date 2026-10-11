from __future__ import annotations

import gzip
import re
import urllib.parse
from typing import Any

from arr.subtitles.base import SubtitleCandidate, SubtitleError
from arr.subtitles.subscene import _extract_srt, _fetch_with

ISO_2_TO_3: dict[str, str] = {
    "en": "eng",
    "es": "spa",
    "fr": "fre",
    "de": "ger",
    "it": "ita",
    "pt": "por",
    "ru": "rus",
    "zh": "chi",
    "ja": "jpn",
    "ko": "kor",
    "nl": "dut",
    "pl": "pol",
    "sv": "swe",
    "da": "dan",
    "fi": "fin",
    "no": "nor",
    "tr": "tur",
    "ar": "ara",
    "he": "heb",
    "vi": "vie",
    "th": "tha",
    "id": "ind",
    "tl": "tag",
    "fil": "fil",
    "hi": "hin",
    "el": "ell",
    "cs": "cze",
    "ro": "rum",
    "hu": "hun",
    "uk": "ukr",
}

ISO_3_TO_2: dict[str, str] = {v: k for k, v in ISO_2_TO_3.items()}


def normalize_to_3letter_lang(lang: str) -> str:
    cleaned = lang.strip().lower()
    return ISO_2_TO_3.get(cleaned, cleaned)


def normalize_to_2letter_lang(lang: str) -> str:
    cleaned = lang.strip().lower()
    return ISO_3_TO_2.get(cleaned, cleaned)


class OpenSubtitlesClient:
    """Client for the free OpenSubtitles REST API (rest.opensubtitles.org).

    Does not require an API key and supports movies and TV series episodes.
    """

    def __init__(
        self,
        base_url: str = "https://rest.opensubtitles.org",
        user_agent: str = "VLSub 0.10.2",
        session: Any = None,
    ) -> None:
        self.base = base_url.rstrip("/")
        self.user_agent = user_agent
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
        lang_list = languages or ["en"]
        lang3_list = [normalize_to_3letter_lang(lang_code) for lang_code in lang_list]
        sublanguageid = ",".join(lang3_list)

        clean_imdb = None
        if imdb_id:
            digits = re.sub(r"[^\d]", "", imdb_id)
            if digits:
                clean_imdb = digits

        is_tv = season is not None and episode is not None

        if is_tv:
            if clean_imdb:
                endpoint = (
                    f"{self.base}/search/episode-{episode}/imdbid-{clean_imdb}/"
                    f"season-{season}/sublanguageid-{sublanguageid}"
                )
            elif title:
                endpoint = (
                    f"{self.base}/search/episode-{episode}/query-{urllib.parse.quote(title)}/"
                    f"season-{season}/sublanguageid-{sublanguageid}"
                )
            else:
                return []
        else:
            if clean_imdb:
                endpoint = f"{self.base}/search/imdbid-{clean_imdb}/sublanguageid-{sublanguageid}"
            elif title:
                encoded_title = urllib.parse.quote(title)
                endpoint = f"{self.base}/search/query-{encoded_title}/sublanguageid-{sublanguageid}"
            else:
                return []

        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
        }

        try:
            resp = _fetch_with(self._session, endpoint, headers=headers)
        except Exception as e:
            raise SubtitleError(f"OpenSubtitles request failed: {e}") from e

        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"OpenSubtitles HTTP {getattr(resp, 'status_code', '?')}")

        try:
            items = resp.json()
        except Exception as e:
            raise SubtitleError(f"Failed to parse OpenSubtitles JSON: {e}") from e

        if not isinstance(items, list):
            return []

        candidates: list[SubtitleCandidate] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            sub_id_raw = item.get("IDSubtitleFile") or item.get("IDSubtitle")
            if not sub_id_raw:
                continue
            try:
                sub_id = int(sub_id_raw)
            except (ValueError, TypeError):
                continue

            dl_link = item.get("SubDownloadLink")
            if not dl_link:
                continue

            rel_name = item.get("MovieReleaseName") or item.get("SubFileName") or ""
            raw_lang = item.get("ISO639") or item.get("SubLanguageID") or "en"
            normalized_lang = normalize_to_2letter_lang(raw_lang)

            try:
                downloads = int(item.get("SubDownloadsCnt") or 0)
            except (ValueError, TypeError):
                downloads = 0

            hi = str(item.get("SubHearingImpaired") or "0") == "1"
            hd = str(item.get("SubHD") or "0") == "1"
            add_date = str(item.get("SubAddDate") or "")

            candidates.append(
                SubtitleCandidate(
                    subtitle_id=sub_id,
                    file_id=sub_id,
                    language=normalized_lang,
                    release_name=rel_name,
                    downloads=downloads,
                    hearing_impaired=hi,
                    hd=hd,
                    upload_date=add_date,
                    download_link=dl_link,
                )
            )

        return candidates

    def download(self, candidate: SubtitleCandidate) -> bytes:
        if not candidate.download_link:
            raise SubtitleError("No download link")

        headers = {
            "User-Agent": self.user_agent,
        }

        try:
            resp = _fetch_with(self._session, candidate.download_link, headers=headers)
        except Exception as e:
            raise SubtitleError(f"OpenSubtitles download failed: {e}") from e

        if getattr(resp, "status_code", 0) != 200:
            raise SubtitleError(f"OpenSubtitles HTTP {getattr(resp, 'status_code', '?')}")

        raw_content = resp.content
        if not raw_content:
            raise SubtitleError("Empty subtitle payload")

        # OpenSubtitles links serve gzip-compressed .srt payloads
        try:
            content = gzip.decompress(raw_content)
        except Exception:
            content = raw_content

        return _extract_srt(content)
