from datetime import date

from arr.core.models import Episode, Season, Series
from arr.db import DB
from arr.monitor.loop import episode_airs_within_lookahead, select_airing, tick
from arr.series.orchestration import mark_pack_imported, needed_episodes, resolve_scope


def make_series() -> Series:
    return Series(
        tmdb_id=10,
        title="Show",
        year=2020,
        status="Returning Series",
        seasons=[
            Season(
                season_number=1,
                episodes=[
                    Episode(
                        tmdb_id=10, season_number=1, episode_number=1,
                        name="A", air_date="2020-01-01",
                    ),
                    Episode(
                        tmdb_id=10, season_number=1, episode_number=2,
                        name="B", air_date="2020-01-08",
                    ),
                ],
            )
        ],
    )


def test_resolve_scope_whole_series():
    s = make_series()
    assert len(resolve_scope(s)) == 2


def test_resolve_scope_season():
    s = make_series()
    assert len(resolve_scope(s, season=1)) == 2
    assert resolve_scope(s, season=2) == []


def test_resolve_scope_episode():
    s = make_series()
    eps = resolve_scope(s, season=1, episode=2)
    assert len(eps) == 1 and eps[0].name == "B"


def test_needed_episodes_skips_imported(tmp_path):
    db = DB(tmp_path / "t.db")
    s = make_series()
    db.set_episode_state(10, 1, 1, "imported")
    needed = needed_episodes(s, db)
    assert [e.episode_number for e in needed] == [2]
    db.close()


def test_mark_pack_imported(tmp_path):
    db = DB(tmp_path / "t.db")
    s = make_series()
    n = mark_pack_imported(db, s, 1)
    assert n == 2
    assert db.episode_state(10, 1, 1) == "imported"
    assert db.episode_state(10, 1, 2) == "imported"
    db.close()


def test_select_airing_respects_lookahead(tmp_path):
    db = DB(tmp_path / "t.db")
    s = make_series()
    assert len(select_airing(s, db, today=date(2020, 1, 1), lookahead_days=7)) == 2
    assert len(select_airing(s, db, today=date(2019, 12, 1), lookahead_days=0)) == 0
    db.close()


def test_tick_enqueues_once(tmp_path):
    db = DB(tmp_path / "t.db")
    db.add_monitored(10, "Show", "tt10", "Returning Series", None)
    calls = []

    def enqueue(series, eps):
        calls.append([e.episode_number for e in eps])
        for e in eps:
            db.set_episode_state(series.tmdb_id, e.season_number, e.episode_number, "queued")
        return len(eps)

    fake_cfg = type("C", (), {"get": lambda s, k, d=None: 7})()
    first = tick(
        db, fake_cfg, series_fetcher=lambda _: make_series(),
        enqueue=enqueue, today=date(2020, 1, 10),
    )
    assert first == [10]
    # second tick: episodes now 'queued' -> not enqueued again (idempotent)
    second = tick(
        db, fake_cfg, series_fetcher=lambda _: make_series(),
        enqueue=enqueue, today=date(2020, 1, 10),
    )
    assert second == []
    assert len(calls) == 1
    db.close()


def test_tick_indexer_failure_marks_retry_pending(tmp_path):
    db = DB(tmp_path / "t.db")
    db.add_monitored(10, "Show", "tt10", "Returning Series", None)

    def enqueue(series, eps):
        raise RuntimeError("indexer down")

    fake_cfg = type("C", (), {"get": lambda s, k, d=None: 7})()
    tick(
        db, fake_cfg, series_fetcher=lambda _: make_series(),
        enqueue=enqueue, today=date(2020, 1, 10),
    )
    assert db.episode_state(10, 1, 1) == "retry_pending"
    assert db.episode_state(10, 1, 2) == "retry_pending"
    db.close()


def test_episode_airs_within_lookahead():
    ep = Episode(tmdb_id=1, season_number=1, episode_number=1, air_date="2020-01-08")
    assert episode_airs_within_lookahead(ep, date(2020, 1, 1), 7)
    assert not episode_airs_within_lookahead(ep, date(2020, 1, 1), 6)
    assert episode_airs_within_lookahead(ep, date(2020, 2, 1), 0)  # already aired counts


def test_is_ended_status():
    from arr.monitor.loop import is_ended_status

    assert is_ended_status("Ended")
    assert is_ended_status("Canceled")
    assert is_ended_status("Cancelled")
    assert not is_ended_status("Returning Series")
    assert not is_ended_status(None)


def test_tick_unmonitors_finished_ended_series(tmp_path):
    db = DB(tmp_path / "t.db")
    db.add_monitored(10, "Show", "tt10", "Ended", None)
    # all episodes already imported -> nothing wanted
    db.set_episode_state(10, 1, 1, "imported")
    db.set_episode_state(10, 1, 2, "imported")

    def enqueue(series, eps):
        raise AssertionError("should not enqueue for a finished ended series")

    ended = make_series()
    ended.status = "Ended"
    values = {"unmonitor_ended_series": True, "monitor_lookahead_days": 7}
    fake_cfg = type("C", (), {"get": lambda s, k, d=None: values.get(k, d)})()
    tick(
        db, fake_cfg, series_fetcher=lambda _: ended,
        enqueue=enqueue, today=date(2020, 1, 10),
    )
    assert db.list_monitored() == []
    db.close()


def test_tick_keeps_ended_series_by_default(tmp_path):
    db = DB(tmp_path / "t.db")
    db.add_monitored(10, "Show", "tt10", "Ended", None)
    db.set_episode_state(10, 1, 1, "imported")
    db.set_episode_state(10, 1, 2, "imported")

    def enqueue(series, eps):
        return len(eps)

    ended = make_series()
    ended.status = "Ended"
    values = {"unmonitor_ended_series": False, "monitor_lookahead_days": 7}
    fake_cfg = type("C", (), {"get": lambda s, k, d=None: values.get(k, d)})()
    tick(
        db, fake_cfg, series_fetcher=lambda _: ended,
        enqueue=enqueue, today=date(2020, 1, 10),
    )
    assert len(db.list_monitored()) == 1
    db.close()
