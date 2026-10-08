from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field


class MediaType(StrEnum):
    MOVIE = "movie"
    TV = "tv"


class DownloadScope(StrEnum):
    SERIES = "series"
    SEASON = "season"
    EPISODE = "episode"


class DownloadState(StrEnum):
    QUEUED = "queued"
    ADDED = "added"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    IMPORTED = "imported"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRY_PENDING = "retry_pending"


class SubtitleSource(StrEnum):
    EMBEDDED = "embedded"
    SIBLING = "sibling"
    SUBSCENE = "subscene"
    YIFY = "yify"
    MISSING = "missing"


class SeedingPolicyMode(StrEnum):
    RATIO = "ratio"
    TIME = "time"
    MANUAL = "manual"
    REMOVE_ON_IMPORT = "remove_on_import"


class Query(BaseModel):
    media_type: MediaType
    text: str = ""
    tmdb_id: int | None = None
    imdb_id: str | None = None
    tvdb_id: int | None = None
    title: str | None = None
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    season_pack: bool = False
    limit: int = 50


class Release(BaseModel):
    indexer: str
    title: str
    infohash: str
    magnet: str
    media_type: MediaType
    seeds: int = 0
    peers: int = 0
    size_bytes: int = 0
    quality: str | None = None
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    is_pack: bool = False
    tmdb_id: int | None = None
    imdb_id: str | None = None

    # guessit enrichment
    resolution: str | None = None
    source: str | None = None
    codec: str | None = None
    group: str | None = None
    is_proper: bool = False
    is_repack: bool = False


class QualityProfile(BaseModel):
    resolutions: list[str] = Field(default_factory=lambda: ["2160p", "1080p", "720p"])
    source_order: list[str] = Field(
        default_factory=lambda: ["BluRay", "WEB-DL", "WEBRip", "HDTV"]
    )
    codecs: list[str] = Field(default_factory=lambda: ["x265", "x264", "AV1", "HEVC"])
    min_seeders: int = 1
    min_size_bytes: int | None = None
    max_size_bytes: int | None = None


class Episode(BaseModel):
    tmdb_id: int
    season_number: int
    episode_number: int
    name: str = ""
    air_date: str | None = None


class Season(BaseModel):
    season_number: int
    episodes: list[Episode] = Field(default_factory=list)


class Series(BaseModel):
    tmdb_id: int
    title: str
    year: int | None = None
    imdb_id: str | None = None
    tvdb_id: int | None = None
    status: str = ""
    seasons: list[Season] = Field(default_factory=list)

    def all_episodes(self) -> list[Episode]:
        out: list[Episode] = []
        for s in self.seasons:
            out.extend(s.episodes)
        return out


class MonitoredSeries(BaseModel):
    id: int | None = None
    tmdb_id: int
    imdb_id: str | None = None
    title: str
    status: str = ""
    quality: str | None = None
    last_checked_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DownloadRecord(BaseModel):
    infohash: str
    media_type: MediaType
    tmdb_id: int | None = None
    title: str = ""
    season: int | None = None
    episode: int | None = None
    indexer: str = ""
    state: DownloadState = DownloadState.QUEUED
    download_dir: str | None = None
    content_path: str | None = None
    destination_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SubtitleRecord(BaseModel):
    media_path: str
    language: str
    source: SubtitleSource
    state: str
    subtitle_id: int | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SeedingPolicy(BaseModel):
    mode: SeedingPolicyMode = SeedingPolicyMode.RATIO
    seed_ratio: float = 1.0
    seed_time_hours: float = 24.0


@runtime_checkable
class Adapter(Protocol):
    name: str

    def supports(self, media_type: MediaType) -> bool: ...

    async def search(self, q: Query) -> list[Release]: ...


def utc_now() -> datetime:
    return datetime.now(UTC)
