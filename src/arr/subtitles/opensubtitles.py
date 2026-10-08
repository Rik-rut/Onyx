from __future__ import annotations

import difflib
from dataclasses import dataclass

import httpx


@dataclass
class SubtitleCandidate:
    subtitle_id: int
    file_id: int
    language: str
    release_name: str
    downloads: int
    hearing_impaired: bool
    hd: bool
    upload_date: str
    download_link: str | None = None


class OpenSubtitlesError(Exception):
    pass


class QuotaExceeded(OpenSubtitlesError):
    pass


def rank_candidates(
    candidates: list[SubtitleCandidate],
    *,
    release_name: str,
    forced_only: bool = False,
) -> list[SubtitleCandidate]:
    pool = [c for c in candidates if (not forced_only or c.hearing_impaired)]
    if not pool:
        return []
    return sorted(
        pool,
        key=lambda c: (
            0 if c.hearing_impaired else 1,
            -c.downloads,
            -difflib.SequenceMatcher(None, c.release_name.lower(), release_name.lower()).ratio(),
            _neg_date(c.upload_date),
        ),
    )


def _neg_date(s: str) -> str:
    return "".join(chr(255 - ord(ch)) if ch.isprintable() else ch for ch in s)


class OpenSubtitlesClient:
    DEFAULT_BASE = "https://api.opensubtitles.com/api/v1"
    BASE = DEFAULT_BASE

    def __init__(self, api_key: str, base_url: str | None = None):
        if not api_key:
            raise OpenSubtitlesError("opensubtitles_api_key is not configured")
        self.api_key = api_key
        self.BASE = (base_url or OpenSubtitlesClient.DEFAULT_BASE).rstrip("/")
        self.headers = {"Api-Key": api_key, "User-Agent": "arr v0.1"}

    def search(
        self,
        *,
        imdb_id: str | None = None,
        tmdb_id: int | None = None,
        season: int | None = None,
        episode: int | None = None,
        languages: list[str] | None = None,
    ) -> list[SubtitleCandidate]:
        params: dict = {}
        if imdb_id:
            params["imdb_id"] = imdb_id.lstrip("t")
        if tmdb_id:
            params["tmdb_id"] = tmdb_id
        if season is not None:
            params["season_number"] = season
        if episode is not None:
            params["episode_number"] = episode
        if languages:
            params["languages"] = ",".join(languages)
        try:
            with httpx.Client(timeout=20.0) as c:
                resp = c.get(f"{self.BASE}/subtitles", params=params, headers=self.headers)
        except httpx.HTTPError as e:
            raise OpenSubtitlesError(f"OpenSubtitles request failed: {e}") from e
        if resp.status_code == 429:
            raise QuotaExceeded("OpenSubtitles daily quota exhausted")
        if resp.status_code != 200:
            raise OpenSubtitlesError(f"OpenSubtitles HTTP {resp.status_code}")
        data = resp.json()
        out: list[SubtitleCandidate] = []
        for item in data.get("data", []) or []:
            attrs = item.get("attributes", {})
            files = attrs.get("files") or [{}]
            f0 = files[0] if files else {}
            out.append(
                SubtitleCandidate(
                    subtitle_id=_to_int(item.get("id")) or 0,
                    file_id=_to_int(f0.get("file_id")) or 0,
                    language=attrs.get("language", "en"),
                    release_name=(attrs.get("release") or attrs.get("movie_name") or f0.get("file_name") or ""),
                    downloads=_to_int(attrs.get("download_count")) or 0,
                    hearing_impaired=bool(attrs.get("hearing_impaired")),
                    hd=bool(attrs.get("hd")),
                    upload_date=str(attrs.get("upload_date") or ""),
                )
            )
        return out

    def download_link(self, file_id: int) -> str:
        try:
            with httpx.Client(timeout=20.0) as c:
                resp = c.post(f"{self.BASE}/download", json={"file_id": file_id}, headers=self.headers)
        except httpx.HTTPError as e:
            raise OpenSubtitlesError(str(e)) from e
        if resp.status_code == 429:
            raise QuotaExceeded("OpenSubtitles daily quota exhausted")
        if resp.status_code != 200:
            raise OpenSubtitlesError(f"OpenSubtitles HTTP {resp.status_code}")
        data = resp.json()
        link = data.get("link")
        if not link:
            raise OpenSubtitlesError("No download link returned")
        return link


def _to_int(v) -> int | None:
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None
