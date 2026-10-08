from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from arr.core.models import Episode, MonitoredSeries, Series
from arr.db import DB


def episode_airs_within_lookahead(ep: Episode, today: date | None = None, lookahead_days: int = 7) -> bool:
    if not ep.air_date:
        return False
    try:
        air = datetime.strptime(ep.air_date, "%Y-%m-%d").date()
    except ValueError:
        return False
    today = today or date.today()
    return air <= today + timedelta(days=lookahead_days)


def select_airing(
    series: Series,
    db: DB,
    *,
    today: date | None = None,
    lookahead_days: int = 7,
) -> list[Episode]:
    """Episodes whose air_date is today/past or within lookahead, not already imported/downloading."""
    out: list[Episode] = []
    for ep in series.all_episodes():
        if not episode_airs_within_lookahead(ep, today, lookahead_days):
            continue
        state = db.episode_state(series.tmdb_id, ep.season_number, ep.episode_number)
        if state in ("imported", "downloading", "queued", "added", "completed"):
            continue
        out.append(ep)
    return out


def tick(
    db: DB,
    cfg,
    *,
    series_fetcher: Callable[[int], Series],
    enqueue: Callable[[Series, list[Episode]], int],
    today: date | None = None,
    lookahead_days: int | None = None,
) -> list[int]:
    """Run one monitor tick. Returns tmdb_ids that had episodes enqueued."""
    lookahead = lookahead_days if lookahead_days is not None else int(cfg.get("monitor_lookahead_days", 7))
    enqueued_for: list[int] = []
    for m in db.list_monitored():
        try:
            series = series_fetcher(int(m["tmdb_id"]))
        except Exception as e:
            import sys

            print(f"warning: monitor tick skipping {m['title']}: {e}", file=sys.stderr)
            continue
        db.set_last_checked(int(m["id"]), _now())
        wanted = select_airing(series, db, today=today, lookahead_days=lookahead)
        if not wanted:
            continue
        try:
            n = enqueue(series, wanted)
        except Exception as e:
            import sys

            print(f"warning: enqueue failed for {m['title']}: {e}", file=sys.stderr)
            for ep in wanted:
                db.set_episode_state(series.tmdb_id, ep.season_number, ep.episode_number, "retry_pending")
            continue
        if n:
            enqueued_for.append(int(m["tmdb_id"]))
    return enqueued_for


def _now() -> float:
    import time

    return time.time()
