from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Protocol


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


class SubtitleProvider(Protocol):
    def search(
        self,
        *,
        imdb_id: str | None = None,
        tmdb_id: int | None = None,
        title: str | None = None,
        season: int | None = None,
        episode: int | None = None,
        languages: list[str] | None = None,
    ) -> list[SubtitleCandidate]: ...

    def download(self, candidate: SubtitleCandidate) -> bytes: ...


class SubtitleError(Exception):
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
