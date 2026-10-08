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


def test_enqueue_queues_beyond_concurrency_limit(tmp_path, monkeypatch):
    """With max_concurrent_downloads=1 and no active torrents, the 2nd+ are queued."""
    cfg = make_cfg(tmp_path, max_concurrent_downloads=1)
    db = DB(tmp_path / "arr.db")

    added: list[dict] = []

    class Rpc:
        def __init__(self, *a, **k):
            pass

        async def list_torrents(self):
            return []

        async def add_magnet(self, magnet, download_dir, paused=False):
            added.append({"magnet": magnet, "paused": paused})
            return {}

        async def start(self, torrent_id):
            return {}

    monkeypatch.setattr(pipeline, "_rpc", lambda c: Rpc())

    async def fake_fan_out(q, c):
        return [fake_release(q.episode)]

    monkeypatch.setattr(pipeline, "_fan_out", fake_fan_out)
    n = asyncio.run(
        pipeline._enqueue_episodes(
            make_series(), pipeline.resolve_scope(make_series()), cfg, db
        )
    )
    assert n == 2
    # first starts, second is queued (paused)
    assert added[0]["paused"] is False
    assert added[1]["paused"] is True
    assert db.get_download(fake_release(1).infohash)["state"] == "added"
    assert db.get_download(fake_release(2).infohash)["state"] == "queued"
    db.close()


def test_enqueue_prefers_season_pack(tmp_path, monkeypatch):
    """When a season pack is available and prefer_packs is on, one torrent covers the season."""
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")

    added: list[str] = []

    class Rpc:
        def __init__(self, *a, **k):
            pass

        async def list_torrents(self):
            return []

        async def add_magnet(self, magnet, download_dir, paused=False):
            added.append(magnet)
            return {}

        async def start(self, torrent_id):
            return {}

    monkeypatch.setattr(pipeline, "_rpc", lambda c: Rpc())

    pack = Release(
        indexer="eztv",
        title="Show S01 COMPLETE 1080p WEB-DL x264",
        infohash="packabc".ljust(40, "0"),
        magnet="magnet:?xt=urn:btih:packabc",
        media_type=MediaType.TV,
        seeds=500,
        size_bytes=8_000_000_000,
        is_pack=True,
    )

    async def fake_fan_out(q, c):
        return [pack, fake_release(q.episode)]

    monkeypatch.setattr(pipeline, "_fan_out", fake_fan_out)
    n = asyncio.run(
        pipeline._enqueue_episodes(
            make_series(), pipeline.resolve_scope(make_series()), cfg, db, prefer_packs=True
        )
    )
    assert n == 1
    assert len(added) == 1
    assert db.episode_state(10, 1, 1) == "added"
    assert db.episode_state(10, 1, 2) == "added"
    db.close()


def test_enqueue_pack_disabled_adds_per_episode(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")
    added: list[str] = []

    class Rpc:
        def __init__(self, *a, **k):
            pass

        async def list_torrents(self):
            return []

        async def add_magnet(self, magnet, download_dir, paused=False):
            added.append(magnet)
            return {}

        async def start(self, torrent_id):
            return {}

    monkeypatch.setattr(pipeline, "_rpc", lambda c: Rpc())

    pack = Release(
        indexer="eztv",
        title="Show S01 COMPLETE 1080p",
        infohash="packxyz".ljust(40, "0"),
        magnet="magnet:?xt=urn:btih:packxyz",
        media_type=MediaType.TV, seeds=500, size_bytes=8_000_000_000, is_pack=True,
    )

    async def fake_fan_out(q, c):
        return [pack, fake_release(q.episode)]

    monkeypatch.setattr(pipeline, "_fan_out", fake_fan_out)
    n = asyncio.run(
        pipeline._enqueue_episodes(
            make_series(), pipeline.resolve_scope(make_series()), cfg, db, prefer_packs=False
        )
    )
    assert n == 2
    assert len(added) == 2
    db.close()


def test_group_by_season_and_pick_pack():
    from arr.core.models import Release as R
    from arr.series.orchestration import group_by_season, pick_season_pack

    eps = make_series().all_episodes()
    groups = group_by_season(eps)
    assert set(groups) == {1} and len(groups[1]) == 2
    pack = R(
        indexer="x", title="Show S01 COMPLETE", infohash="h".ljust(40, "0"),
        magnet="magnet:?xt=urn:btih:h", media_type=MediaType.TV, is_pack=True,
    )
    ep = fake_release(1)
    assert pick_season_pack([ep, pack]) is pack
    assert pick_season_pack([ep]) is None


def test_poll_and_import_only_imports_completed(tmp_path, monkeypatch):
    """A dir existing is not completion; only state=='completed' is imported."""
    cfg = make_cfg(tmp_path)
    db = DB(tmp_path / "arr.db")
    content = tmp_path / "downloads" / "movies" / ".incomplete" / "Inception.2010"
    content.mkdir(parents=True)
    (content / "Inception.2010.1080p.mkv").write_bytes(b"\x00" * 1024)
    # 'downloading' record with an existing staging dir must NOT be imported
    db.add_download(
        "aaa".ljust(40, "0"), media_type="movie", title="Inception", year=2010,
        download_dir=str(content), state="downloading",
    )
    n = pipeline._poll_and_import(cfg, db)
    assert n == 0
    assert db.get_download("aaa".ljust(40, "0"))["state"] == "downloading"
    # now completed -> imported
    db.set_download_state("aaa".ljust(40, "0"), "completed")
    n2 = pipeline._poll_and_import(cfg, db)
    assert n2 == 1
    assert db.get_download("aaa".ljust(40, "0"))["state"] == "imported"
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
