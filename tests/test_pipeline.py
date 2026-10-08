"""Integration-style tests for the download/import/monitor orchestration.

Network and transmission are stubbed so these run fully offline.
"""

import asyncio

from arr import pipeline
from arr.config.settings import DEFAULTS, Config
from arr.core.models import Episode, MediaType, Release, Season, Series
from arr.db import DB


def make_cfg(tmp_path, **over):
    values = dict(
        DEFAULTS,
        download_root=str(tmp_path / "downloads"),
        library_root=str(tmp_path / "downloads"),
        import_mode="copy",
        **over,
    )
    return Config(values=values)


def make_series() -> Series:
    return Series(
        tmdb_id=10,
        title="Show",
        year=2020,
        imdb_id="tt10",
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


def fake_release(ep, seeds=100):
    return Release(
        indexer="fake",
        title=f"Show S01E{ep:02d} 1080p WEB-DL x264",
        infohash=f"hash{ep:02d}".ljust(40, "0"),
        magnet=f"magnet:?xt=urn:btih:hash{ep:02d}",
        media_type=MediaType.TV,
        seeds=seeds,
        peers=1,
        size_bytes=2_000_000_000,
    )


class FakeRpc:
    added: list[tuple[str, str]] = []

    def __init__(self, *a, **k):
        pass

    async def add_magnet(self, magnet, download_dir, paused=False):
        FakeRpc.added.append((magnet, download_dir))
        return {}


def test_enqueue_episodes_adds_one_torrent_per_missing_episode(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")
    monkeypatch.setattr(pipeline, "_rpc", lambda c: FakeRpc())
    FakeRpc.added = []

    calls: list[tuple] = []

    async def fake_fan_out(q, c):
        calls.append((q.season, q.episode))
        return [fake_release(q.episode)]

    monkeypatch.setattr(pipeline, "_fan_out", fake_fan_out)

    n = asyncio.run(
        pipeline._enqueue_episodes(
            make_series(), pipeline.resolve_scope(make_series()), cfg, db
        )
    )
    assert n == 2
    assert calls == [(1, 1), (1, 2)]
    assert len(FakeRpc.added) == 2
    # state recorded
    assert db.episode_state(10, 1, 1) == "added"
    assert db.get_download(fake_release(1).infohash) is not None
    # re-running is idempotent (episodes now 'added')
    n2 = asyncio.run(
        pipeline._enqueue_episodes(
            make_series(), pipeline.resolve_scope(make_series()), cfg, db
        )
    )
    assert n2 == 0
    assert len(FakeRpc.added) == 2
    db.close()


def test_enqueue_episodes_dedupes_shared_infohash(tmp_path, monkeypatch):
    """A season pack (same infohash for both eps) is only added once."""
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")
    monkeypatch.setattr(pipeline, "_rpc", lambda c: FakeRpc())
    FakeRpc.added = []

    pack = Release(
        indexer="fake",
        title="Show S01 COMPLETE 1080p",
        infohash="packhash".ljust(40, "0"),
        magnet="magnet:?xt=urn:btih:packhash",
        media_type=MediaType.TV,
        seeds=50,
        size_bytes=5_000_000_000,
    )

    async def fake_fan_out(q, c):
        return [pack]

    monkeypatch.setattr(pipeline, "_fan_out", fake_fan_out)
    n = asyncio.run(
        pipeline._enqueue_episodes(
            make_series(), pipeline.resolve_scope(make_series()), cfg, db
        )
    )
    assert n == 1
    assert len(FakeRpc.added) == 1
    db.close()


def test_enqueue_respects_passed_scope(tmp_path, monkeypatch):
    """Only episodes in the caller's scope are enqueued, not the whole series."""
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")
    monkeypatch.setattr(pipeline, "_rpc", lambda c: FakeRpc())
    FakeRpc.added = []

    async def fake_fan_out(q, c):
        return [fake_release(q.episode)]

    monkeypatch.setattr(pipeline, "_fan_out", fake_fan_out)
    series = make_series()
    scope = pipeline.resolve_scope(series, season=1, episode=2)
    n = asyncio.run(pipeline._enqueue_episodes(series, scope, cfg, db))
    assert n == 1
    assert len(FakeRpc.added) == 1
    assert db.episode_state(10, 1, 2) == "added"
    assert db.episode_state(10, 1, 1) is None
    db.close()


def test_import_movie_record(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")
    content = tmp_path / "downloads" / "movies" / ".incomplete" / "Inception.2010.1080p"
    content.mkdir(parents=True)
    (content / "Inception.2010.1080p.mkv").write_bytes(b"\x00" * 2048)
    (content / "Inception.2010.1080p.eng.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    db.add_download(
        "abc123".ljust(40, "0"), media_type="movie", title="Inception", year=2010,
        download_dir=str(content), state="completed",
    )
    rec = db.get_download("abc123".ljust(40, "0"))
    final = pipeline._import_record(rec, cfg, db)
    assert final is not None and final.exists()
    assert final == tmp_path / "downloads" / "movies" / "Inception (2010)" / "Inception (2010).mkv"
    assert (final.parent / "Inception (2010).en.srt").exists()
    assert db.get_download(rec["infohash"])["state"] == "imported"
    db.close()


def test_import_episode_record_moves_subtitle(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")
    content = tmp_path / "downloads" / "tv-shows" / ".incomplete" / "pack"
    content.mkdir(parents=True)
    (content / "Show.S01E02.1080p.mkv").write_bytes(b"\x01" * 1024)
    (content / "Show.S01E02.1080p.en.srt").write_text("subs")
    db.add_download(
        "def456".ljust(40, "0"), media_type="tv", title="Show", year=2020, tmdb_id=10,
        imdb_id="tt10", season=1, episode=2, episode_title="B",
        download_dir=str(content), state="completed",
    )
    rec = db.get_download("def456".ljust(40, "0"))
    final = pipeline._import_record(rec, cfg, db)
    assert final is not None
    assert final.parent.name == "Season 01"
    assert final.name == "Show - S01E02 - B.mkv"
    assert (final.parent / "Show - S01E02 - B.en.srt").exists()
    assert db.episode_state(10, 1, 2) == "imported"
    db.close()


def test_import_season_pack_distributes_all_episodes(tmp_path, monkeypatch):
    db = DB(tmp_path / "arr.db")
    content = tmp_path / "downloads" / "tv-shows" / ".incomplete" / "seasonpack"
    content.mkdir(parents=True)
    (content / "Show.S01E01.mkv").write_bytes(b"a" * 512)
    (content / "Show.S01E02.mkv").write_bytes(b"b" * 512)
    series = make_series()
    db.add_monitored(10, "Show", "tt10", "Returning Series", None)
    db.set_episode_state(10, 1, 1, "imported")
    n = pipeline.mark_pack_imported(db, series, 1)
    assert n == 2
    db.close()


def test_series_remove_delete_files(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    sid = db.add_monitored(10, "Show", "tt10", "Ended", None)
    show_dir = tmp_path / "downloads" / "tv-shows" / "Show (2020)" / "Season 01"
    show_dir.mkdir(parents=True)
    (show_dir / "Show - S01E01 - A.mkv").write_bytes(b"x")
    db.close()

    pipeline.series_remove(sid, cfg, delete_files=True)
    assert not (tmp_path / "downloads" / "tv-shows" / "Show (2020)").exists()
    db2 = pipeline._db(cfg)
    assert db2.list_monitored() == []
    db2.close()
