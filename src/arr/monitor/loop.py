from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta

from arr.core.models import Episode, Series
from arr.db import DB


def episode_airs_within_lookahead(
    ep: Episode, today: date | None = None, lookahead_days: int = 7
) -> bool:
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
    """Episodes whose air_date is today/past or within lookahead, not already downloaded."""
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
    """Run one monitor tick. Returns tmdb_ids that had episodes enqueued.

    When ``unmonitor_ended_series`` is true, monitored shows whose status is
    ``Ended``/``Canceled`` and that have no remaining episodes to download are
    removed from monitoring.
    """
    if lookahead_days is not None:
        lookahead = lookahead_days
    else:
        lookahead = int(cfg.get("monitor_lookahead_days", 7))
    unmonitor_ended = bool(cfg.get("unmonitor_ended_series", False))
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
        if is_ended_status(series.status) and unmonitor_ended and not wanted:
            db.remove_monitored(int(m["id"]))
            continue
        if not wanted:
            continue
        try:
            n = enqueue(series, wanted)
        except Exception as e:
            import sys

            print(f"warning: enqueue failed for {m['title']}: {e}", file=sys.stderr)
            for ep in wanted:
                db.set_episode_state(
                    series.tmdb_id, ep.season_number, ep.episode_number, "retry_pending"
                )
            continue
        if n:
            enqueued_for.append(int(m["tmdb_id"]))
    return enqueued_for


ENDED_STATUSES = {"Ended", "Canceled", "Cancelled"}


def is_ended_status(status: str | None) -> bool:
    return str(status or "").strip() in ENDED_STATUSES


def _now() -> float:
    import time

    return time.time()
