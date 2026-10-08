from __future__ import annotations

from arr.core.models import Episode, Series
from arr.db import DB


def resolve_scope(series: Series, season: int | None = None, episode: int | None = None) -> list[Episode]:
    eps: list[Episode] = []
    seasons = series.seasons
    if season is not None:
        seasons = [s for s in seasons if s.season_number == season]
    for s in seasons:
        for e in s.episodes:
            if episode is not None and e.episode_number != episode:
                continue
            eps.append(e)
    return eps


def seasons_in_scope(series: Series, season: int | None = None, episode: int | None = None) -> list[int]:
    if season is not None:
        return [season]
    if episode is not None:
        # episode-only scope implies all seasons containing that episode number
        return [s.season_number for s in series.seasons if any(e.episode_number == episode for e in s.episodes)]
    return [s.season_number for s in series.seasons]


def needed_episodes(series: Series, db: DB, *, season: int | None = None, episode: int | None = None) -> list[Episode]:
    out: list[Episode] = []
    for e in resolve_scope(series, season, episode):
        state = db.episode_state(series.tmdb_id, e.season_number, e.episode_number)
        if state in ("imported", "downloading", "queued", "added", "completed"):
            continue
        out.append(e)
    return out


def mark_pack_imported(db: DB, series: Series, season: int) -> int:
    count = 0
    for s in series.seasons:
        if s.season_number != season:
            continue
        for e in s.episodes:
            db.set_episode_state(series.tmdb_id, season, e.episode_number, "imported")
            count += 1
    return count


def episodes_in_season(series: Series, season: int) -> list[Episode]:
    for s in series.seasons:
        if s.season_number == season:
            return list(s.episodes)
    return []
