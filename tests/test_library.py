"""Library management: badges, covers, and the per-title actions (delete, seeding, tracking)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest
from starlette.testclient import TestClient

from arr import pipeline
from arr.config.settings import DEFAULTS, Config
from arr.core.models import Series
from arr.interactive.library_view import get_library_shows
from arr.metadata.matching import pick_match
from arr.metadata.posters import PosterResolver
from arr.metadata.tvmaze import TvmazeClient
from arr.web.app import create_app

HASH = "a" * 40


def make_cfg(tmp_path: Path) -> Config:
    values = dict(
        DEFAULTS,
        download_root=str(tmp_path / "downloads"),
        library_root=str(tmp_path / "downloads"),
    )
    return Config(values=values)


@pytest.fixture
def test_cfg(tmp_path: Path) -> Config:
    return make_cfg(tmp_path)


@pytest.fixture
def client(test_cfg: Config) -> TestClient:
    return TestClient(create_app(test_cfg))


@pytest.fixture(autouse=True)
def _no_real_daemon():
    with patch("arr.pipeline.ensure_daemon", return_value=None):
        yield


def make_movie(cfg: Config, name: str = "Inception (2010)") -> Path:
    folder = Path(str(cfg.get("library_root"))) / "movies" / name
    folder.mkdir(parents=True)
    media = folder / f"{name}.mkv"
    media.write_bytes(b"x" * 256)
    return media


def make_show(cfg: Config, name: str = "Show (2020)") -> Path:
    season = Path(str(cfg.get("library_root"))) / "tv-shows" / name / "Season 01"
    season.mkdir(parents=True)
    episode = season / "Show - S01E01 - A.mkv"
    episode.write_bytes(b"a" * 128)
    return episode


def link_movie(cfg: Config, media: Path, infohash: str = HASH) -> None:
    db = pipeline._db(cfg)
    db.add_download(
        infohash, media_type="movie", title="Inception", year=2010, imdb_id="tt1375666",
        state="queued",
    )
    db.set_download_state(
        infohash, "imported", destination_path=str(media), content_path=str(media.parent)
    )
    db.close()


def live_torrent(infohash: str = HASH, torrent_id: int = 7) -> dict:
    return {
        "id": torrent_id,
        "hashString": infohash,
        "name": "Inception",
        "percentDone": 1.0,
        "status": 6,
    }


TVMAZE_STUBS = dict(
    search_tv=lambda self, query: {"id": 10, "title": "Show", "year": 2020},
    full_series=lambda self, tmdb_id: Series(
        tmdb_id=10, title="Show", year=2020, imdb_id="tt10", status="Ended"
    ),
    tv_details=lambda self, tmdb_id: Series(
        tmdb_id=10, title="Show", year=2020, imdb_id="tt10", status="Ended"
    ),
    search_tv_shows=lambda self, query: [
        {"id": 10, "title": "Show", "year": 2020, "poster": "https://img.example/show.jpg"}
    ],
    tv_show_summary=lambda self, show_id: {"poster": "https://img.example/show.jpg"},
)


def stub_tvmaze():
    """Patch the TVMaze client methods used by the disk scan and the library routes."""
    from contextlib import ExitStack

    stack = ExitStack()
    for name, fn in TVMAZE_STUBS.items():
        stack.enter_context(patch.object(TvmazeClient, name, fn))
    return stack


def test_library_shows_report_monitored_episodes(tmp_path: Path) -> None:
    """The Library badge reads the monitored series by tmdb_id.

    The lookup used a non-existent `series_id` key, and the KeyError was swallowed,
    so tracked shows never showed the Monitored badge.
    """
    cfg = make_cfg(tmp_path)
    episode = make_show(cfg)

    db = pipeline._db(cfg)
    db.add_monitored(tmdb_id=10, title="Show", imdb_id="tt10", status="Ended", quality=None)
    db.set_episode_state(10, 1, 1, "imported", path=str(episode))
    db.close()

    shows = get_library_shows(Path(str(cfg.get("library_root"))) / "tv-shows", cfg)

    assert len(shows) == 1
    assert shows[0]["monitored_count"] == 1


def test_untrack_survives_the_disk_scan(tmp_path: Path) -> None:
    """A show untracked by the user must not be re-tracked by the next disk scan."""
    cfg = make_cfg(tmp_path)
    make_show(cfg)

    with stub_tvmaze():
        db = pipeline._db(cfg)
        pipeline.sync_disk_library(cfg, db)
        assert [s["title"] for s in db.list_monitored()] == ["Show"]

        row = db.list_monitored()[0]
        assert db.untrack_series(int(row["id"])) is True
        assert db.list_monitored() == []

        pipeline.sync_disk_library(cfg, db)
        assert db.list_monitored() == []
        db.close()


def test_tracking_again_clears_the_untrack_marker(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    db = pipeline._db(cfg)
    series_id = db.add_monitored(
        tmdb_id=10, title="Show", imdb_id="tt10", status="Ended", quality=None
    )
    db.untrack_series(series_id)
    assert db.is_untracked("Show") is True

    db.add_monitored(tmdb_id=10, title="Show", imdb_id="tt10", status="Ended", quality=None)

    assert db.is_untracked("Show") is False
    db.close()


def test_series_tab_unmonitor_is_kept_by_library_rescans(
    client: TestClient, test_cfg: Config
) -> None:
    make_show(test_cfg)
    db = pipeline._db(test_cfg)
    series_id = db.add_monitored(
        tmdb_id=10, title="Show", imdb_id="tt10", status="Ended", quality=None
    )
    db.close()

    with stub_tvmaze():
        assert client.delete(f"/api/series/{series_id}").status_code == 200
        assert client.get("/api/library").status_code == 200

    db = pipeline._db(test_cfg)
    assert db.list_monitored() == []
    db.close()


def test_library_listing_reports_covers_seeding_and_tracking(
    client: TestClient, test_cfg: Config
) -> None:
    media = make_movie(test_cfg)
    link_movie(test_cfg, media)
    make_show(test_cfg)
    db = pipeline._db(test_cfg)
    db.add_monitored(tmdb_id=10, title="Show", imdb_id="tt10", status="Ended", quality=None)
    db.close()

    with (
        stub_tvmaze(),
        patch(
            "arr.transmission.process.RpcClient.list_torrents",
            new_callable=AsyncMock,
            return_value=[live_torrent()],
        ),
    ):
        data = client.get("/api/library").json()

    movie = data["movies"][0]
    assert movie["name"] == "Inception (2010)"
    assert movie["year"] == 2010
    assert movie["imdb_id"] == "tt1375666"
    assert movie["seeding"] is True
    expected_poster = "/api/library/poster?kind=movie&name=" + quote("Inception (2010)", safe="")
    assert movie["poster"] == expected_poster

    show = data["shows"][0]
    assert show["monitored"] is True
    assert show["tmdb_id"] == 10
    assert show["seeding"] is False
    assert show["poster"] == "/api/library/poster?kind=tv&name=" + quote("Show (2020)", safe="")


def test_library_poster_redirects_to_cover_art(client: TestClient, test_cfg: Config) -> None:
    make_movie(test_cfg)
    with patch.object(
        PosterResolver, "movie_poster", return_value="https://img.example/inception.jpg"
    ):
        resp = client.get(
            "/api/library/poster?kind=movie&name=Inception%20(2010)", follow_redirects=False
        )
    assert resp.status_code == 302
    assert resp.headers["location"] == "https://img.example/inception.jpg"


def test_library_poster_is_404_without_cover_art(client: TestClient, test_cfg: Config) -> None:
    make_movie(test_cfg)
    with patch.object(PosterResolver, "movie_poster", return_value=""):
        resp = client.get(
            "/api/library/poster?kind=movie&name=Inception%20(2010)", follow_redirects=False
        )
    assert resp.status_code == 404


def test_library_delete_requires_confirmation(client: TestClient, test_cfg: Config) -> None:
    media = make_movie(test_cfg)
    resp = client.post(
        "/api/library/delete", json={"kind": "movie", "name": "Inception (2010)"}
    )
    assert resp.status_code == 422
    assert media.exists()


def test_library_delete_removes_files_torrent_and_record(
    client: TestClient, test_cfg: Config
) -> None:
    media = make_movie(test_cfg)
    link_movie(test_cfg, media)
    with (
        patch(
            "arr.transmission.process.RpcClient.list_torrents",
            new_callable=AsyncMock,
            return_value=[live_torrent()],
        ),
        patch(
            "arr.transmission.process.RpcClient.remove", new_callable=AsyncMock
        ) as mock_remove,
    ):
        resp = client.post(
            "/api/library/delete",
            json={"kind": "movie", "name": "Inception (2010)", "confirm": True},
        )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    mock_remove.assert_called_once_with(7, delete_data=True)
    assert not media.parent.exists()
    db = pipeline._db(test_cfg)
    assert db.get_download(HASH) is None
    db.close()


def test_library_delete_untracks_show_and_clears_its_episodes(
    client: TestClient, test_cfg: Config
) -> None:
    episode = make_show(test_cfg)
    db = pipeline._db(test_cfg)
    db.add_monitored(tmdb_id=10, title="Show", imdb_id="tt10", status="Ended", quality=None)
    db.set_episode_state(10, 1, 1, "imported", path=str(episode))
    db.close()

    with patch(
        "arr.transmission.process.RpcClient.list_torrents",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = client.post(
            "/api/library/delete",
            json={"kind": "tv", "name": "Show (2020)", "confirm": True},
        )
    assert resp.status_code == 200
    assert resp.json()["untracked"] is True
    assert not episode.parent.parent.exists()
    db = pipeline._db(test_cfg)
    assert db.list_monitored() == []
    assert db.episode_state(10, 1, 1) is None
    db.close()


def test_library_actions_refuse_names_outside_the_library(
    client: TestClient, test_cfg: Config
) -> None:
    root = Path(str(test_cfg.get("library_root")))
    root.mkdir(parents=True, exist_ok=True)
    victim = root / "secret.txt"
    victim.write_text("keep", encoding="utf-8")

    resp = client.post(
        "/api/library/delete",
        json={"kind": "movie", "name": "../secret.txt", "confirm": True},
    )
    assert resp.status_code == 404
    assert victim.exists()


def test_library_remove_seed_keeps_files_and_library_entry(
    client: TestClient, test_cfg: Config
) -> None:
    media = make_movie(test_cfg)
    link_movie(test_cfg, media)
    with (
        patch(
            "arr.transmission.process.RpcClient.list_torrents",
            new_callable=AsyncMock,
            return_value=[live_torrent()],
        ),
        patch(
            "arr.transmission.process.RpcClient.remove", new_callable=AsyncMock
        ) as mock_remove,
    ):
        resp = client.post(
            "/api/library/remove-seed", json={"kind": "movie", "name": "Inception (2010)"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "seed_removed", "removed": 1}
    mock_remove.assert_called_once_with(7, delete_data=False)
    assert media.exists()
    db = pipeline._db(test_cfg)
    assert db.get_download(HASH)["state"] == "imported"
    db.close()


def test_library_remove_seed_reports_when_nothing_is_seeding(
    client: TestClient, test_cfg: Config
) -> None:
    make_movie(test_cfg)
    with patch(
        "arr.transmission.process.RpcClient.list_torrents",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = client.post(
            "/api/library/remove-seed", json={"kind": "movie", "name": "Inception (2010)"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "not_seeding", "removed": 0}


def test_library_track_and_untrack_round_trip(client: TestClient, test_cfg: Config) -> None:
    make_show(test_cfg)
    with stub_tvmaze():
        assert client.get("/api/library").json()["shows"][0]["monitored"] is True

        resp = client.post("/api/library/untrack", json={"kind": "tv", "name": "Show (2020)"})
        assert resp.status_code == 200
        assert client.get("/api/library").json()["shows"][0]["monitored"] is False

        resp = client.post("/api/library/track", json={"kind": "tv", "name": "Show (2020)"})
        assert resp.status_code == 200
        assert client.get("/api/library").json()["shows"][0]["monitored"] is True


def test_library_track_is_tv_only(client: TestClient, test_cfg: Config) -> None:
    make_movie(test_cfg)
    resp = client.post("/api/library/track", json={"kind": "movie", "name": "Inception (2010)"})
    assert resp.status_code == 400


def test_pick_match_prefers_title_and_year() -> None:
    items = [
        {"title": "Friends", "year": 1994},
        {"title": "The Apothecary Diaries", "year": 2023},
        {"title": "The Apothecary Diaries", "year": 2025},
    ]
    assert pick_match(items, "The Apothecary Diaries", 2025)["year"] == 2025
    # Shows fall back to the title alone: a folder year is often a later season's year.
    assert pick_match(items, "The Apothecary Diaries", 2019)["year"] == 2023
    assert pick_match(items, "Missing", 2020) is None
    # Movies must agree on the year, so a same-titled remake is not picked.
    assert pick_match([{"title": "Heat", "year": 1995}], "Heat", 2010, require_year=True) is None


def test_poster_resolver_caches_hits_and_misses(tmp_path: Path) -> None:
    cfg = make_cfg(tmp_path)
    resolver = PosterResolver(cfg)
    calls: list[str] = []

    def found(imdb_id):
        calls.append(imdb_id)
        return "https://img.example/x.jpg"

    with patch("arr.metadata.posters.ImdbClient.poster_for_imdb_id", side_effect=found):
        assert resolver.movie_poster("Inception", 2010, "tt1375666") == "https://img.example/x.jpg"
        assert resolver.movie_poster("Inception", 2010, "tt1375666") == "https://img.example/x.jpg"
    assert calls == ["tt1375666"]

    failing: list[str] = []

    def offline(imdb_id):
        failing.append(imdb_id)
        raise RuntimeError("imdb offline")

    with patch("arr.metadata.posters.ImdbClient.poster_for_imdb_id", side_effect=offline):
        assert resolver.movie_poster("Heat", 1995, "tt0113277") == ""
        assert resolver.movie_poster("Heat", 1995, "tt0113277") == ""
    assert failing == ["tt0113277"]
