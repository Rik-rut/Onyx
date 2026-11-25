"""Integration-style tests for the download/import/monitor orchestration.

Network and transmission are stubbed so these run fully offline.
"""

import asyncio

from arr import pipeline
from arr.config.settings import DEFAULTS, Config
from arr.core.models import Episode, MediaType, Release, Season, Series
from arr.metadata.tvmaze import TvmazeError
from arr.db import DB


def make_cfg(tmp_path, **over):
    values = dict(
        DEFAULTS,
        download_root=str(tmp_path / "downloads"),
        library_root=str(tmp_path / "downloads"),
    )
    values.update({"import_mode": "copy", **over})
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


def test_resolve_content_rejects_shared_staging_root(tmp_path):
    """A completed record with no content_path must not import the .incomplete root."""
    staging = tmp_path / "downloads" / "movies" / ".incomplete"
    staging.mkdir(parents=True)
    (staging / "some_other_torrent.mkv").write_bytes(b"x")
    rec = {"download_dir": str(staging), "content_path": None}
    assert pipeline._resolve_content(rec) is None
    # a specific per-torrent directory is acceptable
    specific = staging / "Inception.2010"
    specific.mkdir()
    assert pipeline._resolve_content(
        {"download_dir": str(specific), "content_path": None}
    ) == specific
    # content_path always wins
    assert pipeline._resolve_content(
        {"download_dir": str(staging), "content_path": str(specific)}
    ) == specific


def test_cancel_unknown_exits_3(tmp_path):
    import pytest

    cfg = make_cfg(tmp_path)
    with pytest.raises(SystemExit) as e:
        asyncio.run(pipeline.cancel_download("nope", cfg))
    assert e.value.code == 3


def test_cancel_removes_record_when_daemon_unreachable(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    db.add_download("c".ljust(40, "0"), media_type="movie", title="X", state="added")
    db.close()

    from arr.transmission.errors import DependencyUnavailable

    class Rpc:
        def __init__(self, *a, **k):
            pass

        async def list_torrents(self):
            raise DependencyUnavailable("down")

        async def remove(self, *a, **k):
            raise DependencyUnavailable("down")

    monkeypatch.setattr(pipeline, "_rpc", lambda c: Rpc())
    asyncio.run(pipeline.cancel_download("c".ljust(40, "0"), cfg))
    db = pipeline._db(cfg)
    assert db.get_download("c".ljust(40, "0")) is None
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


def test_staging_dir_direct_destination_no_incomplete(tmp_path):
    cfg = make_cfg(tmp_path)
    movie_dir = pipeline._staging_dir(cfg, "movie")
    tv_dir = pipeline._staging_dir(cfg, "tv")

    assert ".incomplete" not in movie_dir.parts
    assert ".incomplete" not in tv_dir.parts
    assert movie_dir.name == "movies"
    assert tv_dir.name == "tv-shows"
    assert movie_dir.exists()
    assert tv_dir.exists()


def test_staging_dir_isolated_from_library_roots(tmp_path):
    """R2.1: raw torrent data stages in downloads/.staging, never in the library."""
    cfg = make_cfg(tmp_path)
    movie_dir = pipeline._staging_dir(cfg, "movie")
    tv_dir = pipeline._staging_dir(cfg, "tv")

    assert movie_dir.parts[-2:] == (".staging", "movies")
    assert tv_dir.parts[-2:] == (".staging", "tv-shows")
    assert movie_dir.parent == tv_dir.parent
    assert (tmp_path / "downloads" / ".staging") == movie_dir.parent
    # neither staging folder lives inside the browsable library roots
    assert (tmp_path / "downloads" / "movies") not in movie_dir.parents
    assert (tmp_path / "downloads" / "tv-shows") not in tv_dir.parents


class FakeImportRpc:
    def __init__(self):
        self.removed: list[tuple] = []

    async def remove(self, torrent_id, delete_data=False):
        self.removed.append((torrent_id, delete_data))
        return {}

    async def list_torrents(self):
        return []


def test_move_import_deletes_raw_release_folder_and_torrent(tmp_path, monkeypatch):
    """R2.2: a move import leaves exactly one clean folder and drops the torrent."""
    cfg = make_cfg(tmp_path, import_mode="move")
    content = tmp_path / "downloads" / ".staging" / "movies" / "Inception.2010.1080p.BluRay"
    content.mkdir(parents=True)
    (content / "Inception.2010.1080p.BluRay.mkv").write_bytes(b"\x00" * 2048)
    (content / "Inception.2010.1080p.BluRay.eng.srt").write_text("subs")
    (content / "www.YTS.AM.jpg").write_bytes(b"junk")
    (content / "YIFYStatus.com.txt").write_text("junk")

    db = DB(tmp_path / "arr.db")
    hash_ = "e" * 40
    db.add_download(
        hash_, media_type="movie", title="Inception", year=2010,
        download_dir=str(content), state="completed",
    )
    rec = db.get_download(hash_)

    rpc = FakeImportRpc()
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)
    monkeypatch.setattr(pipeline, "ensure_subtitles", lambda *a, **k: None)
    mirrored: list[tuple] = []
    monkeypatch.setattr(
        pipeline, "_mirror_subtitles_to_content", lambda c, f: mirrored.append((c, f))
    )

    final = pipeline._import_record(rec, cfg, db)

    assert final is not None and final.exists()
    assert final == tmp_path / "downloads" / "movies" / "Inception (2010)" / "Inception (2010).mkv"
    assert (final.parent / "Inception (2010).en.srt").exists()
    # the raw release folder is gone: only the clean folder remains
    assert not content.exists()
    assert [p.name for p in (tmp_path / "downloads" / "movies").iterdir()] == ["Inception (2010)"]
    # the torrent itself is removed with its data
    assert rpc.removed == [(hash_, True)]
    # move mode must not copy subtitles back into the raw release folder
    assert mirrored == []
    db.close()


def test_copy_import_keeps_raw_folder_and_mirrors_nothing(tmp_path, monkeypatch):
    """Copy/hardlink imports keep the raw folder (seeding) — only move cleans up."""
    cfg = make_cfg(tmp_path, import_mode="copy")
    content = tmp_path / "downloads" / ".staging" / "movies" / "Inception.2010.1080p.BluRay"
    content.mkdir(parents=True)
    (content / "Inception.2010.1080p.BluRay.mkv").write_bytes(b"\x00" * 2048)

    db = DB(tmp_path / "arr.db")
    hash_ = "f" * 40
    db.add_download(
        hash_, media_type="movie", title="Inception", year=2010,
        download_dir=str(content), state="completed",
    )
    rec = db.get_download(hash_)

    rpc = FakeImportRpc()
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)
    monkeypatch.setattr(pipeline, "ensure_subtitles", lambda *a, **k: None)

    final = pipeline._import_record(rec, cfg, db)

    assert final is not None and final.exists()
    assert content.exists()  # raw folder kept for seeding
    assert rpc.removed == []
    db.close()


def test_move_import_season_pack_cleans_raw_pack(tmp_path, monkeypatch):
    """R2.2: season packs move into Season NN and the raw pack folder is deleted."""
    cfg = make_cfg(tmp_path, import_mode="move")
    content = tmp_path / "downloads" / ".staging" / "tv-shows" / "Show.S01.1080p.WEB"
    content.mkdir(parents=True)
    (content / "Show.S01E01.mkv").write_bytes(b"a" * 512)
    (content / "Show.S01E02.mkv").write_bytes(b"b" * 512)
    (content / "poster.jpg").write_bytes(b"junk")

    db = DB(tmp_path / "arr.db")
    hash_ = "9" * 40
    db.add_download(
        hash_, media_type="tv", title="Show", year=2020, tmdb_id=10, season=1,
        download_dir=str(content), state="completed",
    )
    rec = db.get_download(hash_)

    rpc = FakeImportRpc()
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)
    monkeypatch.setattr(pipeline, "ensure_subtitles", lambda *a, **k: None)

    final = pipeline._import_record(rec, cfg, db)

    season_dir = tmp_path / "downloads" / "tv-shows" / "Show (2020)" / "Season 01"
    assert final is not None and season_dir.exists()
    assert sorted(p.name for p in season_dir.iterdir()) == [
        "Show - S01E01.mkv",
        "Show - S01E02.mkv",
    ]
    assert not content.exists()
    assert rpc.removed == [(hash_, True)]
    assert db.episode_state(10, 1, 1) == "imported"
    db.close()


def test_list_queue_excludes_skipped(tmp_path):
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    db.add_download(
        "active".ljust(40, "0"), media_type="movie", title="Active", state="downloading"
    )
    db.add_download(
        "skipped".ljust(40, "0"), media_type="movie", title="Cancelled", state="skipped"
    )
    db.close()

    items = pipeline.list_queue(cfg)
    titles = [it["title"] for it in items]
    assert "Active" in titles
    assert "Cancelled" not in titles


def test_enqueue_release_allows_redownloading_skipped(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    rel = fake_release(1)
    db.add_download(rel.infohash, media_type="tv", title="Old", state="skipped")
    db.close()

    class Rpc:
        def __init__(self, *a, **k):
            pass

        async def list_torrents(self):
            return []

        async def add_magnet(self, *a, **k):
            return {"id": 1}

    monkeypatch.setattr(pipeline, "_rpc", lambda c: Rpc())

    ok, msg = asyncio.run(pipeline.enqueue_release(rel, cfg, media_type="tv"))
    assert ok is True
    assert "downloading" in msg.lower() or "queued" in msg.lower()

    db2 = pipeline._db(cfg)
    rec = db2.get_download(rel.infohash)
    assert rec["state"] in ("added", "downloading", "queued")
    db2.close()


def test_resolve_content_direct_and_fuzzy(tmp_path):
    # 1. Direct content_path
    f1 = tmp_path / "movie.mp4"
    f1.write_bytes(b"data")
    assert pipeline._resolve_content({"content_path": str(f1)}) == f1

    # 2. Fuzzy scan in staging directory
    movies_dir = tmp_path / "movies"
    movies_dir.mkdir()
    actual_folder = movies_dir / "Inception.2010.1080p.BluRay.x264"
    actual_folder.mkdir()
    (actual_folder / "Inception.mp4").write_bytes(b"data")

    # Record has different raw title but matching significant tokens
    rec = {
        "download_dir": str(movies_dir),
        "title": "Inception 2010 1080p",
    }
    resolved = pipeline._resolve_content(rec)
    assert resolved == actual_folder


def test_resolve_content_rpc_fallback(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    content_dir = tmp_path / "rpc_downloads"
    content_dir.mkdir()
    file_path = content_dir / "Actual.Torrent.Name"
    file_path.mkdir()

    class RpcMock:
        async def list_torrents(self):
            return [
                {
                    "hashString": "testhash123",
                    "name": "Actual.Torrent.Name",
                    "downloadDir": str(content_dir),
                }
            ]

    monkeypatch.setattr(pipeline, "_rpc", lambda c: RpcMock())

    rec = {
        "infohash": "testhash123",
        "title": "Some Other Title",
        "download_dir": str(tmp_path / "movies"),
    }
    resolved = pipeline._resolve_content(rec, cfg=cfg)
    assert resolved == file_path


def test_download_magnet_uri(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    added_magnets = []

    class RpcMock:
        async def add_magnet(self, uri, dl_dir):
            added_magnets.append((uri, dl_dir))
            return {
                "torrent-added": {
                    "hashString": "11112222333344445555",
                    "name": "Inception 2010",
                }
            }

        async def set_speed_limits(self, **kwargs):
            return {}

    monkeypatch.setattr(pipeline, "_rpc", lambda c: RpcMock())

    mag = "magnet:?xt=urn:btih:11112222333344445555&dn=Inception+2010"
    h = asyncio.run(pipeline.download_magnet(mag, cfg))
    assert h == "11112222333344445555"
    assert len(added_magnets) == 1

    db = pipeline._db(cfg)
    rec = db.get_download("11112222333344445555")
    assert rec is not None
    assert rec["state"] == "downloading"
    assert rec["media_type"] == "movie"
    db.close()


def test_download_magnet_torrent_file(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    torrent_file = tmp_path / "Breaking.Bad.S01E01.720p.torrent"
    torrent_file.write_bytes(b"dummy torrent bytes")

    class RpcMock:
        async def add_magnet(self, uri, dl_dir):
            return {
                "torrent-added": {
                    "hashString": "bbbb2222333344445555",
                    "name": "Breaking Bad S01E01",
                }
            }

        async def set_speed_limits(self, **kwargs):
            return {}

    monkeypatch.setattr(pipeline, "_rpc", lambda c: RpcMock())

    h = asyncio.run(pipeline.download_magnet(str(torrent_file), cfg))
    assert h == "bbbb2222333344445555"

    db = pipeline._db(cfg)
    rec = db.get_download("bbbb2222333344445555")
    assert rec is not None
    assert rec["media_type"] == "tv"
    assert rec["season"] == 1
    assert rec["episode"] == 1
    db.close()


def test_pause_resume_priority(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    db.add_download("testpausehash", media_type="movie", title="Pause Movie")
    db.close()

    rpc_actions = []

    class RpcMock:
        async def pause_torrent(self, h):
            rpc_actions.append(("pause", h))
            return {}

        async def resume_torrent(self, h):
            rpc_actions.append(("resume", h))
            return {}

        async def set_torrent_priority(self, h, pri):
            rpc_actions.append(("priority", h, pri))
            return {}

    monkeypatch.setattr(pipeline, "_rpc", lambda c: RpcMock())

    # Pause
    asyncio.run(pipeline.pause_download("testpausehash", cfg))
    assert rpc_actions[-1] == ("pause", "testpausehash")
    db = pipeline._db(cfg)
    assert db.get_download("testpausehash")["state"] == "paused"
    db.close()

    # Resume
    asyncio.run(pipeline.resume_download("testpausehash", cfg))
    assert rpc_actions[-1] == ("resume", "testpausehash")
    db = pipeline._db(cfg)
    assert db.get_download("testpausehash")["state"] == "downloading"
    db.close()

    # Priority
    asyncio.run(pipeline.set_download_priority("testpausehash", "top", cfg))
    assert rpc_actions[-1] == ("priority", "testpausehash", "top")


def test_apply_speed_limits(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.values["max_download_speed_kbps"] = 2500
    cfg.values["max_upload_speed_kbps"] = 500

    limits_applied = {}

    class RpcMock:
        async def set_speed_limits(self, download_kbps=0, upload_kbps=0):
            limits_applied["down"] = download_kbps
            limits_applied["up"] = upload_kbps
            return {}

    asyncio.run(pipeline.apply_speed_limits(RpcMock(), cfg))
    assert limits_applied == {"down": 2500, "up": 500}


def test_cleanup_duplicate_folders_via_pipeline_repoints_content_path(tmp_path):
    """R2.3: the cfg-level cleanup folds duplicates and repoints SQLite at the clean copy."""
    cfg = make_cfg(tmp_path)
    raw = tmp_path / "downloads" / "movies" / "Green Book (2018) [BluRay] [1080p] [YTS.AM]"
    raw.mkdir(parents=True)
    (raw / "Green.Book.2018.1080p.BluRay.x264-[YTS.AM].mp4").write_bytes(b"x" * 1024)
    clean = tmp_path / "downloads" / "movies" / "Green Book (2018)"
    clean.mkdir(parents=True)
    media = clean / "Green Book (2018).mp4"
    media.write_bytes(b"x" * 1024)

    db = pipeline._db(cfg)
    db.add_download("a" * 40, media_type="movie", title="Green Book", year=2018, state="queued")
    db.set_download_state(
        "a" * 40, "imported", content_path=str(raw), destination_path=str(media)
    )
    db.close()

    removed = pipeline.cleanup_duplicate_folders(cfg)

    assert removed == 1
    assert not raw.exists()
    db = pipeline._db(cfg)
    rec = db.get_download("a" * 40)
    assert rec["content_path"] == str(media)
    assert rec["state"] == "imported"
    db.close()


def test_cleanup_duplicate_folders_noop_without_duplicates(tmp_path):
    cfg = make_cfg(tmp_path)
    lone = tmp_path / "downloads" / "movies" / "Lone Movie (2019)"
    lone.mkdir(parents=True)
    (lone / "Lone Movie (2019).mkv").write_bytes(b"x" * 256)

    assert pipeline.cleanup_duplicate_folders(cfg) == 0
    assert lone.exists()


class FakeImdbClient:
    """Offline IMDb stub returning fixed metadata for a known title."""

    def __init__(self, cfg=None):
        self.cfg = cfg

    def search_movie(self, title: str):
        if title.strip().lower() == "inception":
            return {"title": "Inception", "year": 2010, "imdb_id": "tt1375666", "id": "tt1375666"}
        return None


class FakeTvmazeClient:
    """Offline TVMaze stub: one show with a two-episode first season."""

    def __init__(self, cfg=None):
        pass

    def search_tv(self, query: str):
        if "show" in query.lower():
            return {
                "id": 10,
                "name": "Show",
                "premiered": "2020-01-01",
                "externals": {"imdb": "tt10"},
            }
        return None

    def full_series(self, tmdb_id: int):
        return make_series()


def test_sync_disk_library_indexes_existing_movies(tmp_path, monkeypatch):
    """R3.1: a movie already in downloads/movies becomes an imported record."""
    cfg = make_cfg(tmp_path)
    folder = tmp_path / "downloads" / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    media = folder / "Inception (2010).mkv"
    media.write_bytes(b"x" * 512)
    (folder / "Inception (2010).en.srt").write_text("subs")

    monkeypatch.setattr(pipeline, "ImdbClient", FakeImdbClient)
    db = pipeline._db(cfg)

    stats = pipeline.sync_disk_library(cfg, db)

    assert stats["movies"] == 1
    rows = [r for r in db.list_downloads() if r["media_type"] == "movie"]
    assert len(rows) == 1
    rec = rows[0]
    assert rec["state"] == "imported"
    assert rec["title"] == "Inception"
    assert rec["year"] == 2010
    assert rec["imdb_id"] == "tt1375666"
    assert rec["destination_path"] == str(media)
    # idempotent: a second scan adds nothing
    assert pipeline.sync_disk_library(cfg, db)["movies"] == 0
    assert len([r for r in db.list_downloads() if r["media_type"] == "movie"]) == 1
    db.close()


def test_sync_disk_library_indexes_movie_without_metadata(tmp_path, monkeypatch):
    """Metadata lookups are best effort: disk detection still records the movie."""
    cfg = make_cfg(tmp_path)
    folder = tmp_path / "downloads" / "movies" / "Unknown Indie Film (2019)"
    folder.mkdir(parents=True)
    (folder / "Unknown Indie Film (2019).mp4").write_bytes(b"x" * 256)

    class OfflineImdb:
        def __init__(self, cfg=None):
            pass

        def search_movie(self, title):
            raise RuntimeError("imdb offline")

    monkeypatch.setattr(pipeline, "ImdbClient", OfflineImdb)
    db = pipeline._db(cfg)

    stats = pipeline.sync_disk_library(cfg, db)

    assert stats["movies"] == 1
    rec = [r for r in db.list_downloads() if r["media_type"] == "movie"][0]
    assert rec["title"] == "Unknown Indie Film"
    assert rec["year"] == 2019
    assert rec["imdb_id"] is None
    db.close()


def test_sync_disk_library_monitors_tv_and_marks_on_disk_episodes(tmp_path, monkeypatch):
    """R3.1: on-disk shows are auto-monitored and their episodes marked imported."""
    cfg = make_cfg(tmp_path)
    season = tmp_path / "downloads" / "tv-shows" / "Show (2020)" / "Season 01"
    season.mkdir(parents=True)
    (season / "Show - S01E01 - A.mkv").write_bytes(b"a" * 128)
    (season / "Show - S01E02 - B.mkv").write_bytes(b"b" * 128)

    monkeypatch.setattr(pipeline, "TvmazeClient", FakeTvmazeClient)
    db = pipeline._db(cfg)

    stats = pipeline.sync_disk_library(cfg, db)

    assert stats["shows"] == 1
    assert stats["episodes"] == 2
    monitored = db.list_monitored()
    assert len(monitored) == 1
    assert monitored[0]["title"] == "Show"
    assert monitored[0]["tmdb_id"] == 10
    assert db.episode_state(10, 1, 1) == "imported"
    assert db.episode_state(10, 1, 2) == "imported"
    # episodes not on disk stay untouched (still monitored as missing)
    assert db.episode_state(10, 1, 3) is None
    db.close()


def test_sync_disk_library_survives_offline_metadata(tmp_path, monkeypatch):
    """R3.1: an unreachable TVMaze must not break startup scanning."""
    cfg = make_cfg(tmp_path)
    season = tmp_path / "downloads" / "tv-shows" / "Show (2020)" / "Season 01"
    season.mkdir(parents=True)
    (season / "Show - S01E01 - A.mkv").write_bytes(b"a" * 128)

    class OfflineTv:
        def __init__(self, cfg=None):
            pass

        def search_tv(self, query):
            raise RuntimeError("tvmaze offline")

    monkeypatch.setattr(pipeline, "TvmazeClient", OfflineTv)
    db = pipeline._db(cfg)

    stats = pipeline.sync_disk_library(cfg, db)

    assert stats["shows"] == 1
    assert stats["monitored"] == 0
    assert db.list_monitored() == []
    db.close()


def test_check_media_availability_movie(tmp_path):
    """R3.2: availability is resolved from the disk library."""
    cfg = make_cfg(tmp_path)
    folder = tmp_path / "downloads" / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    media = folder / "Inception (2010).mkv"
    media.write_bytes(b"x" * 512)

    hit = pipeline.check_media_availability(cfg, media_type="movie", title="Inception", year=2010)
    assert hit["in_library"] is True
    assert hit["status"] == "available"
    assert hit["path"] == str(media)

    miss = pipeline.check_media_availability(
        cfg, media_type="movie", title="Inception", year=2011
    )
    assert miss["in_library"] is False
    assert miss["status"] is None

    by_imdb = pipeline.check_media_availability(
        cfg, media_type="movie", title="Something Else", imdb_id="tt1375666"
    )
    assert by_imdb["in_library"] is False  # not recorded in the DB yet


def test_check_media_availability_queued_download(tmp_path):
    """A movie still downloading reports 'queued' rather than available."""
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    db.add_download(
        "q" * 40, media_type="movie", title="Inception", year=2010, state="downloading"
    )
    db.close()

    res = pipeline.check_media_availability(cfg, media_type="movie", title="Inception", year=2010)
    assert res["in_library"] is False
    assert res["status"] == "queued"


def test_check_media_availability_tv_episodes_and_monitoring(tmp_path):
    cfg = make_cfg(tmp_path)
    season = tmp_path / "downloads" / "tv-shows" / "Show (2020)" / "Season 01"
    season.mkdir(parents=True)
    (season / "Show - S01E01 - A.mkv").write_bytes(b"a" * 128)

    db = pipeline._db(cfg)
    db.add_monitored(10, "Show", "tt10", "Returning Series", None)
    db.close()

    show = pipeline.check_media_availability(cfg, media_type="tv", title="Show")
    assert show["in_library"] is True
    assert show["status"] == "partial"  # only some episodes are on disk
    assert show["monitored"] is True
    assert show["available_seasons"] == {"1": [1]}

    present = pipeline.check_media_availability(
        cfg, media_type="tv", title="Show", season=1, episode=1
    )
    assert present["in_library"] is True and present["status"] == "available"

    missing = pipeline.check_media_availability(
        cfg, media_type="tv", title="Show", season=1, episode=5
    )
    assert missing["in_library"] is False
    assert missing["status"] == "monitored"
    assert missing["monitored"] is True


def test_check_media_availability_tv_without_disk_or_db(tmp_path):
    cfg = make_cfg(tmp_path)
    res = pipeline.check_media_availability(cfg, media_type="tv", title="Nothing Here")
    assert res["in_library"] is False
    assert res["status"] is None
    assert res["monitored"] is False


def test_move_import_keeps_raw_folder_when_media_is_unimported(tmp_path, monkeypatch):
    """CR-01: never delete raw media that was not actually imported."""
    cfg = make_cfg(tmp_path, import_mode="move")
    # A season pack recorded as a single episode: only E01 gets imported.
    content = tmp_path / "downloads" / ".staging" / "tv-shows" / "Show.S01.1080p"
    content.mkdir(parents=True)
    for ep in range(1, 4):
        (content / f"Show.S01E{ep:02d}.mkv").write_bytes(bytes([ep]) * 256)

    db = DB(tmp_path / "arr.db")
    hash_ = "1" * 40
    db.add_download(
        hash_, media_type="tv", title="Show", year=2020, tmdb_id=10, season=1, episode=1,
        download_dir=str(content), state="completed",
    )
    rec = db.get_download(hash_)
    rpc = FakeImportRpc()
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)
    monkeypatch.setattr(pipeline, "ensure_subtitles", lambda *a, **k: None)

    final = pipeline._import_record(rec, cfg, db)

    season_dir = tmp_path / "downloads" / "tv-shows" / "Show (2020)" / "Season 01"
    assert final is not None and final.exists()
    assert (season_dir / "Show - S01E01.mkv").exists()
    # the raw folder survives because E02/E03 were never imported
    assert content.exists()
    assert sorted(p.name for p in content.iterdir()) == ["Show.S01E02.mkv", "Show.S01E03.mkv"]
    db.close()


def test_move_import_deletes_raw_folder_once_everything_is_imported(tmp_path, monkeypatch):
    """The happy path still collapses to a single folder (R2.2)."""
    cfg = make_cfg(tmp_path, import_mode="move")
    content = tmp_path / "downloads" / ".staging" / "movies" / "Inception.2010.1080p"
    content.mkdir(parents=True)
    (content / "Inception.2010.1080p.mkv").write_bytes(b"x" * 1024)
    (content / "poster.jpg").write_bytes(b"junk")

    db = DB(tmp_path / "arr.db")
    hash_ = "2" * 40
    db.add_download(
        hash_, media_type="movie", title="Inception", year=2010,
        download_dir=str(content), state="completed",
    )
    rec = db.get_download(hash_)
    monkeypatch.setattr(pipeline, "_rpc", lambda c: FakeImportRpc())
    monkeypatch.setattr(pipeline, "ensure_subtitles", lambda *a, **k: None)

    pipeline._import_record(rec, cfg, db)

    assert not content.exists()
    db.close()


def test_cleanup_keeps_raw_movie_folder_when_everything_is_not_importable(tmp_path):
    """CR-01 in the startup cleanup: two movies in one folder must not lose one."""
    from arr.importer.layout import cleanup_duplicate_folders

    movies = tmp_path / "downloads" / "movies"
    raw = movies / "Double.Feature.2020.1080p.BluRay.x264"
    raw.mkdir(parents=True)
    (raw / "MovieA.2020.1080p.mkv").write_bytes(b"a" * 2048)
    (raw / "MovieB.2021.1080p.mkv").write_bytes(b"b" * 1024)

    cleanup_duplicate_folders(tmp_path / "downloads")

    # The import moved the primary file into a clean folder...
    clean = movies / "Double Feature (2020)"
    assert clean.exists()
    # ...but the second movie must not have been destroyed with the raw folder.
    remaining = list(raw.glob("*.mkv")) if raw.exists() else []
    assert [p.name for p in remaining] == ["MovieB.2021.1080p.mkv"]


def test_check_media_availability_ignores_deleted_destination(tmp_path):
    """IM-01: a record whose file vanished must not report 'available'."""
    cfg = make_cfg(tmp_path)
    missing = tmp_path / "downloads" / "movies" / "Inception (2010)" / "Inception (2010).mkv"
    db = pipeline._db(cfg)
    db.add_download("m" * 40, media_type="movie", title="Inception", year=2010)
    db.set_download_state("m" * 40, "imported", destination_path=str(missing))
    db.close()

    res = pipeline.check_media_availability(cfg, media_type="movie", title="Inception", year=2010)

    assert res["in_library"] is False
    assert res["status"] is None


def test_sync_disk_library_skips_movies_tracked_under_release_names(tmp_path, monkeypatch):
    """IM-02: an imported record for the same movie must not be duplicated."""
    cfg = make_cfg(tmp_path)
    folder = tmp_path / "downloads" / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    media = folder / "Inception (2010).mkv"
    media.write_bytes(b"x" * 512)

    db = pipeline._db(cfg)
    db.add_download(
        "r" * 40,
        media_type="movie",
        title="Inception.2010.1080p.BluRay.x264-[YTS.AG]",
        year=2010,
        state="queued",
    )
    db.set_download_state("r" * 40, "imported", destination_path=str(media))

    monkeypatch.setattr(pipeline, "ImdbClient", FakeImdbClient)
    stats = pipeline.sync_disk_library(cfg, db)

    assert stats["movies"] == 0  # already tracked -> no synthetic disk row
    rows = [r for r in db.list_downloads() if r["media_type"] == "movie"]
    assert len(rows) == 1
    assert not rows[0]["infohash"].startswith("disk-")
    db.close()


def test_delete_media_path_preserves_other_files_subtitles(tmp_path):
    """IM-03: removing one movie must not strip a sibling file's subtitles."""
    cfg = make_cfg(tmp_path)
    folder = tmp_path / "downloads" / "movies" / "Movie (2018)"
    folder.mkdir(parents=True)
    first = folder / "Movie (2018).mkv"
    second = folder / "Movie (2018).2.mkv"
    first.write_bytes(b"1" * 256)
    second.write_bytes(b"2" * 256)
    sibling_sub = folder / "Movie (2018).2.en.srt"
    sibling_sub.write_text("second movie subtitles")
    own_sub = folder / "Movie (2018).en.srt"
    own_sub.write_text("first movie subtitles")

    pipeline._delete_media_path(first, cfg)

    assert not first.exists()
    assert not own_sub.exists()
    assert sibling_sub.exists()  # belongs to the untouched second movie
    assert second.exists()


def test_remove_download_prunes_emptied_parent_dirs(tmp_path, monkeypatch):
    """IM-04: deleting a season/episode directory must prune empty parents."""
    cfg = make_cfg(tmp_path)
    show = tmp_path / "downloads" / "tv-shows" / "Show (2020)"
    season = show / "Season 02"
    season.mkdir(parents=True)
    (season / "Show - S02E01 - A.mkv").write_bytes(b"x" * 256)

    db = pipeline._db(cfg)
    hash_ = "s" * 40
    db.add_download(hash_, media_type="tv", title="Show", year=2020, tmdb_id=10, season=2)
    db.set_download_state(hash_, "imported", content_path=str(season))
    db.close()

    monkeypatch.setattr(pipeline, "_rpc", lambda c: FakeRemoveRpc([]))

    pipeline_result = asyncio.run(pipeline.remove_download_and_files(hash_, cfg))

    assert pipeline_result["deleted_paths"]
    assert not season.exists()
    assert not show.exists()  # empty show parent pruned too
    assert (tmp_path / "downloads" / "tv-shows").exists()


def test_remove_download_refuses_ambiguous_prefix(tmp_path, monkeypatch):
    """MI-02: a prefix matching several infohashes must not delete one of them."""
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    for prefix, title in (("abcd1", "Victim One"), ("abcd2", "Victim Two")):
        hash_ = (prefix * 8)[:40]
        db.add_download(hash_, media_type="movie", title=title, year=2020, state="queued")
    db.close()

    monkeypatch.setattr(pipeline, "_rpc", lambda c: FakeRemoveRpc([]))

    result = asyncio.run(pipeline.remove_download_and_files("abcd", cfg))

    assert result["ambiguous"] is True
    assert result["db_removed"] is False
    db = pipeline._db(cfg)
    assert len([r for r in db.list_downloads() if r["title"].startswith("Victim")]) == 2
    db.close()


def test_remove_disk_detected_movie_skips_transmission(tmp_path, monkeypatch):
    """MI-08: a disk-detected row has no torrent, so no RPC removal is attempted."""
    cfg = make_cfg(tmp_path)
    folder = tmp_path / "downloads" / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    media = folder / "Inception (2010).mkv"
    media.write_bytes(b"x" * 256)

    db = pipeline._db(cfg)
    db.add_download("disk-abc123", media_type="movie", title="Inception", year=2010)
    db.set_download_state("disk-abc123", "imported", destination_path=str(media))
    db.close()

    rpc = FakeRemoveRpc([])
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)

    result = asyncio.run(pipeline.remove_download_and_files("disk-abc123", cfg))

    assert rpc.removed == []  # nothing was sent to Transmission
    assert result["rpc_error"] is None
    assert result["deleted_paths"]
    assert not media.exists()


def test_check_disk_space(tmp_path, monkeypatch):
    from arr.pipeline import check_disk_space

    class StatMock:
        free = 10 * (1024**3)  # 10 GB

    monkeypatch.setattr("shutil.disk_usage", lambda p: StatMock())

    has_space, free_b, req_b = check_disk_space(tmp_path, 5 * (1024**3))
    assert has_space is True
    assert free_b == 10 * (1024**3)
    assert req_b == 5 * (1024**3)

    has_space, free_b, req_b = check_disk_space(tmp_path, 20 * (1024**3))
    assert has_space is False


class FakeRemoveRpc:
    """Transmission RPC stub that reports a numeric-id torrent and records removals."""

    def __init__(self, torrents=None, remove_error=None):
        self.torrents = torrents or []
        self.remove_error = remove_error
        self.removed: list[tuple] = []
        self.listed = 0

    async def list_torrents(self):
        self.listed += 1
        return list(self.torrents)

    async def remove(self, torrent_id, delete_data=False):
        if self.remove_error:
            raise self.remove_error
        self.removed.append((torrent_id, delete_data))
        return {}


def _movie_download(tmp_path, hash_="a" * 40, *, state="imported"):
    """Create a raw release folder + clean library folder for one movie download."""
    raw = tmp_path / "downloads" / "movies" / "Inception.2010.1080p.BluRay.x264-[YTS.AG]"
    raw.mkdir(parents=True)
    (raw / "Inception.2010.1080p.BluRay.x264-[YTS.AG].mp4").write_bytes(b"x" * 512)
    clean = tmp_path / "downloads" / "movies" / "Inception (2010)"
    clean.mkdir(parents=True)
    media = clean / "Inception (2010).mp4"
    media.write_bytes(b"x" * 512)
    (clean / "Inception (2010).en.srt").write_text("subs")
    return raw, clean, media


def test_remove_download_and_files_resolves_numeric_rpc_id(tmp_path, monkeypatch):
    """R1.1/R1.2: a numeric queue id resolves to the infohash, the torrent is
    removed with its data, and both the raw and imported files are deleted."""
    cfg = make_cfg(tmp_path)
    hash_ = "a" * 40
    raw, clean, _media = _movie_download(tmp_path, hash_)
    db = pipeline._db(cfg)
    db.add_download(hash_, media_type="movie", title="Inception", year=2010, state="queued")
    db.set_download_state(
        hash_,
        "imported",
        content_path=str(raw),
        destination_path=str(clean / "Inception (2010).mp4"),
    )
    db.close()

    rpc = FakeRemoveRpc(
        [
            {
                "id": 7,
                "hashString": hash_,
                "name": raw.name,
                "downloadDir": str(raw.parent),
            }
        ]
    )
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)

    result = asyncio.run(pipeline.remove_download_and_files("7", cfg))

    assert rpc.removed == [(7, True)]
    assert result["infohash"] == hash_
    assert result["torrent_removed"] is True
    assert result["db_removed"] is True
    assert not raw.exists()
    assert not clean.exists()  # empty movie folder (and its subtitles) pruned
    assert (tmp_path / "downloads" / "movies").exists()

    db = pipeline._db(cfg)
    assert db.get_download(hash_) is None
    db.close()


def test_remove_download_and_files_deletes_tv_episodes(tmp_path, monkeypatch):
    """R1.2: TV downloads delete every imported episode file and their DB rows."""
    cfg = make_cfg(tmp_path)
    hash_ = "b" * 40
    show = tmp_path / "downloads" / "tv-shows" / "Show (2020)"
    season = show / "Season 01"
    season.mkdir(parents=True)
    ep1 = season / "Show - S01E01 - A.mkv"
    ep2 = season / "Show - S01E02 - B.mkv"
    for f in (ep1, ep2):
        f.write_bytes(b"x" * 128)

    db = pipeline._db(cfg)
    db.add_download(hash_, media_type="tv", title="Show", year=2020, tmdb_id=10, season=1)
    db.set_download_state(hash_, "imported", destination_path=str(ep1))
    db.set_episode_state(10, 1, 1, "imported", infohash=hash_, path=str(ep1))
    db.set_episode_state(10, 1, 2, "imported", infohash=hash_, path=str(ep2))
    db.close()

    rpc = FakeRemoveRpc([])
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)

    asyncio.run(pipeline.remove_download_and_files(hash_, cfg))

    assert rpc.removed == [(hash_, True)]
    assert not ep1.exists() and not ep2.exists()
    assert not season.exists() and not show.exists()
    db = pipeline._db(cfg)
    assert db.get_download(hash_) is None
    assert db.episodes_for_series(10) == []
    db.close()


def test_remove_download_and_files_survives_dead_daemon(tmp_path, monkeypatch):
    """Local data is still removed when Transmission is unreachable."""
    cfg = make_cfg(tmp_path)
    hash_ = "c" * 40
    raw, clean, _media = _movie_download(tmp_path, hash_)
    db = pipeline._db(cfg)
    db.add_download(hash_, media_type="movie", title="Inception", year=2010, state="queued")
    db.set_download_state(
        hash_,
        "imported",
        content_path=str(raw),
        destination_path=str(clean / "Inception (2010).mp4"),
    )
    db.close()

    class DeadRpc:
        async def list_torrents(self):
            raise RuntimeError("daemon down")

        async def remove(self, *a, **k):  # pragma: no cover - must not be reached
            raise AssertionError("remove must not be called on a dead daemon")

    monkeypatch.setattr(pipeline, "_rpc", lambda c: DeadRpc())

    result = asyncio.run(pipeline.remove_download_and_files(hash_, cfg))

    assert result["torrent_removed"] is False
    assert "daemon down" in str(result["rpc_error"])
    assert not raw.exists() and not clean.exists()
    db = pipeline._db(cfg)
    assert db.get_download(hash_) is None
    db.close()


def test_cancel_download_deletes_files_and_record(tmp_path, monkeypatch):
    """R1.1: the CLI cancel path always removes the torrent data and local files."""
    cfg = make_cfg(tmp_path)
    hash_ = "d" * 40
    raw, clean, media = _movie_download(tmp_path, hash_)
    db = pipeline._db(cfg)
    db.add_download(hash_, media_type="movie", title="Inception", year=2010, state="queued")
    db.set_download_state(
        hash_, "imported", content_path=str(raw), destination_path=str(media)
    )
    db.close()

    rpc = FakeRemoveRpc(
        [{"id": 2, "hashString": hash_, "name": raw.name, "downloadDir": str(raw.parent)}]
    )
    monkeypatch.setattr(pipeline, "_rpc", lambda c: rpc)

    asyncio.run(pipeline.cancel_download(hash_, cfg))

    assert rpc.removed == [(2, True)]
    assert not raw.exists() and not clean.exists()
    db = pipeline._db(cfg)
    assert db.get_download(hash_) is None
    db.close()





def test_search_candidates_flags_anime_queries(tmp_path, monkeypatch):
    """2.1: a TVMaze result whose genres include "Anime" marks the query anime
    (adapters omit S/E tokens, the ranker skips the S/E gate); Western shows stay False."""
    cfg = make_cfg(tmp_path)

    def tvmaze_with_genres(genres):
        class FakeTvm:
            def __init__(self, *a, **k):
                pass

            def search_tv(self, query):
                return {
                    "id": 495,
                    "name": "Naruto",
                    "genres": genres,
                    "externals": {"imdb": "tt0409591"},
                }

        monkeypatch.setattr(pipeline, "TvmazeClient", FakeTvm)

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    tvmaze_with_genres(["Action", "Anime", "Fantasy"])
    _, _, anime_q = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Naruto", cfg, season=1)
    )
    assert anime_q.anime is True
    assert anime_q.tmdb_id == 495

    tvmaze_with_genres(["Drama", "Crime"])
    _, _, western_q = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Breaking Bad", cfg, season=2)
    )
    assert western_q.anime is False


def _anime_tvmaze(seasons, tmdb_id=41469, genres=("Action", "Anime"), boom=False):
    """A TVMaze stub that reports the show as anime and serves its season shape."""

    class FakeTvm:
        def __init__(self, *a, **k):
            pass

        def search_tv(self, query):
            return {
                "id": tmdb_id,
                "name": "Demon Slayer",
                "genres": list(genres),
                "externals": {"imdb": "tt2341771"},
            }

        def full_series(self, tid):
            if boom:
                raise TvmazeError("episode listing unavailable")
            return Series(
                tmdb_id=tid,
                title="Demon Slayer",
                seasons=[
                    Season(
                        season_number=number,
                        episodes=[
                            Episode(
                                tmdb_id=tid,
                                season_number=number,
                                episode_number=e,
                            )
                            for e in numbers
                        ],
                    )
                    for number, numbers in seasons
                ],
            )

    return FakeTvm


DEMON_SLAYER_SEASONS = [
    (1, list(range(1, 27))),
    (2, list(range(1, 19))),
    (3, list(range(1, 12))),
    (4, list(range(1, 9))),
]


def test_search_candidates_matches_bare_numbers_for_first_season(tmp_path, monkeypatch):
    """Demon Slayer's TVMaze seasons restart at 1 per arc; season 1's local
    numbers are still the global ones, so bare numbers may scope it."""
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(pipeline, "TvmazeClient", _anime_tvmaze(DEMON_SLAYER_SEASONS))

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    _, _, episode_q = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Demon Slayer", cfg, season=1, episode=1)
    )
    assert episode_q.anime_number_match == [1]

    _, _, season_q = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Demon Slayer", cfg, season=1)
    )
    assert season_q.anime_number_match == list(range(1, 27))


def test_search_candidates_maps_restart_seasons_by_offset(tmp_path, monkeypatch):
    """A season-restarting series with clean data maps local numbers to
    their global position: S2E5 is global 31 (26 preceding + 5)."""
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(pipeline, "TvmazeClient", _anime_tvmaze(DEMON_SLAYER_SEASONS))

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    _, _, episode_q = asyncio.run(
        pipeline.search_candidates(
            MediaType.TV, "Demon Slayer", cfg, season=2, episode=5
        )
    )
    assert episode_q.anime_number_match == [31]

    _, _, season_q = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Demon Slayer", cfg, season=2)
    )
    assert season_q.anime_number_match == list(range(27, 45))


def test_search_candidates_maps_year_based_seasons_by_offset(tmp_path, monkeypatch):
    """Year-based shows (Naruto: 2002-2007, each 1..N) get scoped for every
    season via the offset mapping: (2003, 5) -> global 18."""
    cfg = make_cfg(tmp_path)
    year_based = [
        (2002, list(range(1, 14))),
        (2003, list(range(1, 52))),
        (2004, list(range(1, 52))),
    ]
    monkeypatch.setattr(pipeline, "TvmazeClient", _anime_tvmaze(year_based))

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    _, _, first = asyncio.run(
        pipeline.search_candidates(
            MediaType.TV, "Naruto", cfg, season=2002, episode=1
        )
    )
    assert first.anime_number_match == [1]

    _, _, mapped = asyncio.run(
        pipeline.search_candidates(
            MediaType.TV, "Naruto", cfg, season=2003, episode=5
        )
    )
    assert mapped.anime_number_match == [18]

    _, _, season_only = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Naruto", cfg, season=2003)
    )
    assert season_only.anime_number_match == list(range(14, 65))


def test_search_candidates_keeps_legacy_scoping_for_gapped_numbering(tmp_path, monkeypatch):
    """A season with a numbering gap is neither a slice nor a clean
    restart, so no number filter is applied — title-based behavior."""
    cfg = make_cfg(tmp_path)
    gapped = [
        (1, [1, 2, 4]),  # episode 3 missing
        (2, list(range(1, 11))),
    ]
    monkeypatch.setattr(pipeline, "TvmazeClient", _anime_tvmaze(gapped))

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    _, _, season_q = asyncio.run(
        pipeline.search_candidates(
            MediaType.TV, "Demon Slayer", cfg, season=2, episode=5
        )
    )
    assert season_q.anime_number_match is None


def test_search_candidates_matches_bare_numbers_on_continuous_numbering(tmp_path, monkeypatch):
    """Arc-numbered shows (continuous across seasons) scope every season."""
    cfg = make_cfg(tmp_path)
    globally_numbered = [(1, list(range(1, 27))), (2, list(range(27, 53)))]
    monkeypatch.setattr(pipeline, "TvmazeClient", _anime_tvmaze(globally_numbered))

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    _, _, season_q = asyncio.run(
        pipeline.search_candidates(
            MediaType.TV, "Demon Slayer", cfg, season=2, episode=30
        )
    )
    assert season_q.anime_number_match == [30]

    _, _, season_only = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Demon Slayer", cfg, season=2)
    )
    assert season_only.anime_number_match == list(range(27, 53))


def test_search_candidates_survives_unknown_numbering(tmp_path, monkeypatch):
    """An episode-listing failure leaves the legacy path, not a broken search."""
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(
        pipeline, "TvmazeClient", _anime_tvmaze(DEMON_SLAYER_SEASONS, boom=True)
    )

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    accepted, scored, q = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Demon Slayer", cfg, season=1, episode=1)
    )
    assert q.anime is True and q.anime_number_match is None
    assert accepted == []


def test_search_candidates_leaves_number_match_unset_for_western_shows(tmp_path, monkeypatch):
    """Western shows keep the existing SxxExx gate, untouched by this field."""
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(
        pipeline,
        "TvmazeClient",
        _anime_tvmaze(
            [(1, list(range(1, 27)))], genres=("Drama", "Crime")
        ),
    )

    async def no_releases(q, c):
        return []

    monkeypatch.setattr(pipeline, "_fan_out", no_releases)

    _, _, q = asyncio.run(
        pipeline.search_candidates(MediaType.TV, "Breaking Bad", cfg, season=1, episode=1)
    )
    assert q.anime is False
    assert q.anime_number_match is None
