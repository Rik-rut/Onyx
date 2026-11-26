from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from arr.config.settings import DEFAULTS, Config
from arr.core.models import Episode, MediaType, Release, Season, Series
from arr.core.parsing import Scored
from arr.web.app import create_app


@pytest.fixture
def test_cfg(tmp_path: Path) -> Config:
    vals = dict(DEFAULTS)
    vals["download_root"] = str(tmp_path / "downloads")
    vals["library_root"] = str(tmp_path / "downloads")
    return Config(values=vals)


@pytest.fixture
def client(test_cfg: Config) -> TestClient:
    app = create_app(test_cfg)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_real_daemon():
    """Web tests must never require a locally running Transmission daemon."""
    with patch("arr.pipeline.ensure_daemon", return_value=None):
        yield


def test_index_page(client: TestClient) -> None:
    """R5.x: GET / must serve the compiled SPA entry, never the Vue monolith."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "<!doctype html>" in resp.text
    assert "Onyx — Media Discovery" in resp.text
    assert "/assets/" in resp.text
    for cdn in ("cdn.tailwindcss.com", "unpkg.com", "jsdelivr"):
        assert cdn not in resp.text
    assert 'src="http' not in resp.text and 'href="http' not in resp.text


MOJIBAKE_MARKERS = ("Â", "â€", "â†", "âœ", "âˆ", "Ã")


def test_index_page_has_no_mojibake(client: TestClient) -> None:
    """UTF-8 symbols must never be decoded twice (Â·, â†“, âœ“, âˆž shipped before)."""
    body = client.get("/").text
    for marker in MOJIBAKE_MARKERS:
        assert marker not in body, f"mojibake sequence {marker!r} found in served HTML"
    assert "charset=" in body and "utf-8" in body.lower()
    assert "Onyx — Media Discovery" in body


def test_spa_fallback_serves_entry_on_nested_routes(client: TestClient) -> None:
    """Direct visits and reloads of client routes resolve to the SPA document."""
    entry = client.get("/").text
    for path in ("/queue", "/settings", "/movie/tt1375666", "/tv/42", "/library", "/search"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.text == entry


def test_unknown_api_and_ws_paths_stay_json_404(client: TestClient) -> None:
    """The SPA catch-all must not swallow missing API/WebSocket endpoints."""
    for path in ("/api/nonexistent", "/api/queue/nope/nope", "/ws/queue"):
        resp = client.get(path)
        assert resp.status_code == 404
        assert "json" in resp.headers["content-type"]
        assert "doctype" not in resp.text.lower()


def test_api_search_movies(client: TestClient) -> None:
    mock_results = [{"id": "tt123", "title": "Inception", "year": 2010}]
    with patch("arr.metadata.imdb.ImdbClient.search_movies", return_value=mock_results):
        resp = client.get("/api/search/movies?q=Inception")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Inception"


def test_api_search_tv(client: TestClient) -> None:
    mock_results = [{"id": 1, "title": "Breaking Bad", "year": 2008}]
    with patch("arr.metadata.tvmaze.TvmazeClient.search_tv_shows", return_value=mock_results):
        resp = client.get("/api/search/tv?q=Breaking+Bad")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Breaking Bad"


def test_api_releases_movie(client: TestClient) -> None:
    r = Release(
        indexer="yts",
        title="Inception.2010.1080p",
        infohash="hash123",
        magnet="magnet:?xt=urn:btih:hash123",
        media_type=MediaType.MOVIE,
        seeds=100,
        size_bytes=2000000000,
        resolution="1080p",
    )
    s = Scored(release=r, score={"seeders": 100, "resolution_rank": 0})
    with patch(
        "arr.web.routes.search.search_candidates",
        new_callable=AsyncMock,
        return_value=([r], [s], None),
    ):
        resp = client.get("/api/releases/movie?title=Inception&year=2010")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Inception.2010.1080p"
        assert data[0]["score"] == 1100


def test_api_releases_tv(client: TestClient) -> None:
    r = Release(
        indexer="eztv",
        title="Show.S01E01.720p",
        infohash="hash456",
        magnet="magnet:?xt=urn:btih:hash456",
        media_type=MediaType.TV,
        seeds=20,
        size_bytes=500000000,
        resolution="720p",
    )
    s = Scored(release=r, score={"seeders": 20, "resolution_rank": 2})
    with patch(
        "arr.web.routes.search.search_candidates",
        new_callable=AsyncMock,
        return_value=([r], [s], None),
    ):
        resp = client.get("/api/releases/tv?title=Show&season=1&episode=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["infohash"] == "hash456"
        assert data[0]["score"] == 820


def test_api_releases_tv_pack_accepts_blank_episode(client: TestClient) -> None:
    """A season-pack search sends `episode=` blank; that must not be a 422."""
    with patch(
        "arr.web.routes.search.search_candidates",
        new_callable=AsyncMock,
        return_value=([], [], None),
    ) as mock_search:
        resp = client.get("/api/releases/tv?title=Show&season=2&episode=&pack=true")
    assert resp.status_code == 200
    assert resp.json() == []
    assert mock_search.await_args.kwargs.get("episode") is None
    assert mock_search.await_args.kwargs.get("season") == 2


def test_api_releases_movie_accepts_blank_year_and_imdb(client: TestClient) -> None:
    """Movies without a year send `year=` blank; that must not be a 422 either."""
    with patch(
        "arr.web.routes.search.search_candidates",
        new_callable=AsyncMock,
        return_value=([], [], None),
    ) as mock_search:
        resp = client.get("/api/releases/movie?title=Green%20Book&year=&imdb_id=")
    assert resp.status_code == 200
    assert mock_search.await_args.kwargs.get("year") is None
    assert mock_search.await_args.kwargs.get("imdb_id") is None


BAD_NYAA_TITLE = (
    "[DB] Kimetsu no Yaiba | Demon Slayer: Kimetsu no Yaiba (Season 1+2+3+4+5+Movie) "
    "[Dual Audio 10bit BD1080p][HEVC-x265][BDRip][Sub-Eng-Chi-Jap]-ANiGMA"
)


def _tv(title: str, seeds: int = 50, indexer: str = "fake") -> Release:
    h = (title[:10] or "x").ljust(40, "0")
    return Release(
        indexer=indexer,
        title=title,
        infohash=h,
        magnet=f"magnet:?xt=urn:btih:{h}",
        media_type=MediaType.TV,
        seeds=seeds,
        size_bytes=1_500_000_000,
    )


def test_api_releases_tv_survives_malformed_release_name(client: TestClient) -> None:
    """1.3: the known-bad NYAA pack title used to 500 the endpoint via a
    list-typed release_group; it must now rank cleanly and stay out of the way."""
    good = _tv("Show.S02E05.1080p.WEB-DL.x264")
    bad = _tv(BAD_NYAA_TITLE, indexer="nyaa")

    async def fan_out(q, cfg):
        return [good.model_copy(deep=True), bad.model_copy(deep=True)]

    with patch("arr.pipeline._fan_out", new=fan_out), patch(
        "arr.metadata.tvmaze.TvmazeClient.search_tv", return_value=None
    ):
        resp = client.get("/api/releases/tv?title=Show&season=2")
    assert resp.status_code == 200
    rows = resp.json()
    assert any(row["infohash"] == good.infohash for row in rows)
    # The malformed release must not poison the response either way it ranks.
    bad_rows = [row for row in rows if row["infohash"] == bad.infohash]
    for row in bad_rows:
        assert isinstance(row.get("group"), (str, type(None)))


def test_api_releases_tv_pack_query_returns_only_covering_packs(
    client: TestClient,
) -> None:
    """2.4: pack=true returns only season packs covering the requested season."""
    releases = [
        _tv("Show.S01.COMPLETE.1080p.BluRay.x264", seeds=300),
        _tv("Show.S02.COMPLETE.1080p.BluRay.x264", seeds=50),
        _tv("Show.S03.COMPLETE.1080p.BluRay.x264", seeds=200),
        _tv("Show.S02E05.1080p.WEB-DL.x264", seeds=900),
    ]

    async def fan_out(q, cfg):
        return [r.model_copy(deep=True) for r in releases]

    with patch("arr.pipeline._fan_out", new=fan_out), patch(
        "arr.metadata.tvmaze.TvmazeClient.search_tv", return_value=None
    ):
        resp = client.get("/api/releases/tv?title=Show&season=2&pack=true")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["is_pack"] is True
    assert rows[0]["season_label"] == "S02"

def test_api_releases_tv_episode_query_has_no_packs(
    client: TestClient,
) -> None:
    """2.4: a single-episode request never offers season packs."""
    releases = [
        _tv("Show.S02.COMPLETE.1080p.BluRay.x264", seeds=300),
        _tv("Show.S02E05.1080p.WEB-DL.x264", seeds=50),
    ]
    seen_queries: list = []

    async def fan_out(q, cfg):
        seen_queries.append(q)
        return [r.model_copy(deep=True) for r in releases]

    with patch("arr.pipeline._fan_out", new=fan_out), patch(
        "arr.metadata.tvmaze.TvmazeClient.search_tv", return_value=None
    ):
        resp = client.get("/api/releases/tv?title=Show&season=2&episode=5")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["is_pack"] is False
    assert rows[0]["season_label"] == "S02E05"
    # The exclusion is signalled via the flag, not inferred from episode=.
    assert seen_queries and seen_queries[0].exclude_packs is True
    assert seen_queries[0].episode == 5


def test_api_releases_rows_carry_coverage_fields(client: TestClient) -> None:
    """2.5: rows expose raw_title/season/episode/season_label so the drawer can
    show what a release actually covers."""
    multi = _tv("Show.S01.S02.S03.COMPLETE.1080p.BluRay.x264", seeds=100)
    single = _tv("Show.S02E05.1080p.WEB-DL.x264")
    bare = _tv("Demon Slayer -Kimetsu no Yaiba- 045 [1080p]")

    async def fan_out(q, cfg):
        return [
            multi.model_copy(deep=True),
            single.model_copy(deep=True),
            bare.model_copy(deep=True),
        ]

    with patch("arr.pipeline._fan_out", new=fan_out), patch(
        "arr.metadata.tvmaze.TvmazeClient.search_tv", return_value=None
    ):
        resp = client.get("/api/releases/tv?title=Show&season=2")
    assert resp.status_code == 200
    rows = {row["infohash"]: row for row in resp.json()}
    s_row = rows[single.infohash]
    assert s_row["season"] == 2
    assert s_row["episode"] == 5
    assert s_row["season_label"] == "S02E05"
    assert s_row["raw_title"] == "Show.S02E05.1080p.WEB-DL.x264"
    m_row = rows[multi.infohash]
    assert m_row["seasons"] == [1, 2, 3]
    assert m_row["season_label"] == "S01-S03"
    assert "S01.S02.S03" in (m_row["raw_title"] or "")
    # Anime releases named by bare episode number must say which one they are.
    b_row = rows[bare.infohash]
    assert b_row["season_label"] == "EP045"
    assert b_row["season"] is None
    assert b_row["episode"] == 45


def test_api_releases_tv_best_row_covers_requested_season(
    client: TestClient,
) -> None:
    """3.2: with a mixed S01/S02/S03 candidate set, "Download Best" (client-side
    max score) can no longer pick another season's release."""
    releases = [
        _tv("Show.S01.COMPLETE.2160p.BluRay.x265", seeds=5000),
        _tv("Show.S02.COMPLETE.1080p.BluRay.x264", seeds=50),
        _tv("Show.S03.COMPLETE.1080p.BluRay.x264", seeds=2000),
    ]

    async def fan_out(q, cfg):
        return [r.model_copy(deep=True) for r in releases]

    with patch("arr.pipeline._fan_out", new=fan_out), patch(
        "arr.metadata.tvmaze.TvmazeClient.search_tv", return_value=None
    ):
        resp = client.get("/api/releases/tv?title=Show&season=2")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows, "expected at least one accepted release"
    best = max(rows, key=lambda row: row["score"])
    assert best["season_label"] == "S02"
    # The S01/S03 packs are rejected by the ranker, not just sorted lower.
    assert [row["season_label"] for row in rows] == ["S02"]


def _anime_release(title: str, index: int, seeds: int = 50, media_type=MediaType.TV) -> Release:
    """A distinct release row (infohash from the index, not the shared prefix)."""
    h = f"{index:040d}"
    return Release(
        indexer="nyaa",
        title=title,
        infohash=h,
        magnet=f"magnet:?xt=urn:btih:{h}",
        media_type=media_type,
        seeds=seeds,
        size_bytes=1_500_000_000,
    )


def _demon_slayer_series() -> Series:
    """Demon Slayer's TVMaze shape: four arcs, each numbered from 1."""
    return Series(
        tmdb_id=41469,
        title="Demon Slayer",
        seasons=[
            Season(
                season_number=number,
                episodes=[
                    Episode(
                        tmdb_id=41469,
                        season_number=number,
                        episode_number=e,
                    )
                    for e in range(1, count + 1)
                ],
            )
            for number, count in ((1, 26), (2, 18), (3, 11), (4, 8))
        ],
    )


def test_api_releases_tv_anime_excludes_movies_and_other_seasons(
    client: TestClient,
) -> None:
    """Defect B: the reported "all mixed up" Demon Slayer S1E1 drawer.

    The candidate set mirrors the live baseline that returned 13 rows with zero
    S1E1 — a theatrical movie, an S5-tagged release, a bare episode 45, plus
    the requested bare episode 1 and an unnumbered pack, which must survive.
    """
    movie = _anime_release(
        "Demon Slayer -Kimetsu no Yaiba- The Movie - Infinity Castle (2025) 1080p", 1
    )
    s5 = _anime_release(
        "[Salieri] Demon Slayer -Kimetsu no Yaiba- S5 - Hashira Training Arc (1080p)", 2
    )
    ep45 = _anime_release("Demon Slayer -Kimetsu no Yaiba- 045 [1080p]", 3)
    ep1 = _anime_release("Demon Slayer -Kimetsu no Yaiba- 001 (1080p) [SubsPlease]", 4)
    unnumbered = _anime_release("Demon Slayer -Kimetsu no Yaiba- Season 1-4 + Movie [1080p]", 5)
    releases = [movie, s5, ep45, ep1, unnumbered]
    seen: list = []

    async def fan_out(q, cfg):
        seen.append(q)
        return [r.model_copy(deep=True) for r in releases]

    anime_show = {
        "id": 41469,
        "name": "Demon Slayer",
        "genres": ["Action", "Anime"],
        "externals": {"imdb": "tt2341771"},
    }
    with (
        patch("arr.pipeline._fan_out", new=fan_out),
        patch(
            "arr.metadata.tvmaze.TvmazeClient.search_tv", return_value=anime_show
        ),
        patch(
            "arr.metadata.tvmaze.TvmazeClient.full_series",
            return_value=_demon_slayer_series(),
        ),
    ):
        resp = client.get("/api/releases/tv?title=Demon+Slayer&season=1&episode=1")
    assert resp.status_code == 200
    rows = {row["infohash"]: row for row in resp.json()}
    # Season 1 of a locally-numbered show is still matched by global number.
    assert seen[0].anime is True
    assert seen[0].anime_number_match == [1]
    for gone in (movie, s5, ep45):
        assert gone.infohash not in rows, f"{gone.title!r} must not be offered"
    assert ep1.infohash in rows
    assert rows[ep1.infohash]["season_label"] == "EP001"
    assert unnumbered.infohash in rows


def test_api_releases_tv_anime_season_query_scopes_bare_numbers(
    client: TestClient,
) -> None:
    """The same guarantees at season level: numbers outside 1..26 are out."""
    ep45 = _anime_release("Demon Slayer -Kimetsu no Yaiba- 045 [1080p]", 3)
    ep20 = _anime_release("Demon Slayer -Kimetsu no Yaiba- 020 (1080p) [SubsPlease]", 4)

    async def fan_out(q, cfg):
        return [ep45.model_copy(deep=True), ep20.model_copy(deep=True)]

    anime_show = {"id": 41469, "name": "Demon Slayer", "genres": ["Anime"]}
    with (
        patch("arr.pipeline._fan_out", new=fan_out),
        patch(
            "arr.metadata.tvmaze.TvmazeClient.search_tv", return_value=anime_show
        ),
        patch(
            "arr.metadata.tvmaze.TvmazeClient.full_series",
            return_value=_demon_slayer_series(),
        ),
    ):
        resp = client.get("/api/releases/tv?title=Demon+Slayer&season=1")
    assert resp.status_code == 200
    rows = {row["infohash"]: row for row in resp.json()}
    assert ep20.infohash in rows
    assert rows[ep20.infohash]["season_label"] == "EP020"
    assert ep45.infohash not in rows


def test_api_releases_movie_still_offers_anime_movie_rows(client: TestClient) -> None:
    """The movie drawer must keep working for anime films (NYAA category 1)."""
    movie = _anime_release(
        "Demon Slayer -Kimetsu no Yaiba- The Movie - Infinity Castle (2025) 1080p",
        1,
        media_type=MediaType.MOVIE,
    )

    async def fan_out(q, cfg):
        return [movie.model_copy(deep=True)]

    # IMDb resolves the bare title "Demon Slayer" to the 2019 TV series, and
    # the pre-existing year gate would then reject a 2025 film for reasons
    # unrelated to anime scoping — so the metadata lookup is stubbed out.
    with (
        patch("arr.pipeline._fan_out", new=fan_out),
        patch("arr.metadata.imdb.ImdbClient.search_movie", return_value=None),
    ):
        resp = client.get("/api/releases/movie?title=Demon+Slayer")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["infohash"] == movie.infohash
    assert rows[0]["season_label"] is None


def test_api_search_movies_excludes_tv_typed_entries(client: TestClient) -> None:
    """5.1: IMDb "TV Series" entries must not surface in the Movies section."""
    results = [
        {"id": "tt1", "title": "Dune Part Two", "year": 2024, "type": "Feature"},
        {"id": "tt2", "title": "Naruto", "year": 2002, "type": "TV Series"},
        {"id": "tt3", "title": "Naruto the Movie", "year": 2000, "type": "Feature"},
    ]
    with patch("arr.metadata.imdb.ImdbClient.search_movies", return_value=results):
        resp = client.get("/api/search/movies?q=naruto")
    assert resp.status_code == 200
    titles = [row["title"] for row in resp.json()]
    assert "Naruto" not in titles
    assert "Dune Part Two" in titles
    assert "Naruto the Movie" in titles


def test_queue_delete_removes_torrent_files_and_record(
    client: TestClient, test_cfg: Config
) -> None:
    """R1.2: DELETE /api/queue/{id} removes the torrent, its files, and the DB row."""
    from arr.pipeline import _db

    hash_ = "f" * 40
    raw = Path(test_cfg.get("download_dir") or test_cfg.get("library_root")) / "movies" / (
        "Inception.2010.1080p.BluRay"
    )
    raw.mkdir(parents=True)
    (raw / "Inception.2010.mp4").write_bytes(b"x" * 256)
    clean = Path(test_cfg.get("library_root")) / "movies" / "Inception (2010)"
    clean.mkdir(parents=True)
    (clean / "Inception (2010).mp4").write_bytes(b"x" * 256)

    db = _db(test_cfg)
    db.add_download(hash_, media_type="movie", title="Inception", year=2010, state="queued")
    db.set_download_state(
        hash_,
        "imported",
        content_path=str(raw),
        destination_path=str(clean / "Inception (2010).mp4"),
    )
    db.close()

    torrent = {
        "id": 4,
        "hashString": hash_,
        "name": raw.name,
        "downloadDir": str(raw.parent),
        "percentDone": 1.0,
        "status": 6,
    }
    with (
        patch(
            "arr.transmission.process.RpcClient.list_torrents",
            new_callable=AsyncMock,
            return_value=[torrent],
        ),
        patch(
            "arr.transmission.process.RpcClient.remove", new_callable=AsyncMock
        ) as mock_remove,
    ):
        resp = client.request("DELETE", f"/api/queue/{hash_}", json={"confirm": True})
        assert resp.status_code == 200
        mock_remove.assert_called_once_with(4, delete_data=True)

    assert not raw.exists()
    assert not clean.exists()
    db = _db(test_cfg)
    assert db.get_download(hash_) is None
    db.close()


def test_api_queue_list_and_controls(client: TestClient) -> None:
    t = {
        "id": 1,
        "hashString": "hash1",
        "name": "Movie.mkv",
        "percentDone": 0.75,
        "status": 4,
        "rateDownload": 1024000,
        "rateUpload": 51200,
        "eta": 120,
        "totalSize": 1000000,
    }
    with patch(
        "arr.transmission.process.RpcClient.list_torrents",
        new_callable=AsyncMock,
        return_value=[t],
    ):
        resp = client.get("/api/queue")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Movie.mkv"
        assert data[0]["progress"] == 75.0
        assert data[0]["status"] == "Downloading"

    with patch("arr.transmission.process.RpcClient.stop", new_callable=AsyncMock) as mock_stop:
        resp = client.post("/api/queue/1/pause")
        assert resp.status_code == 200
        mock_stop.assert_called_once_with(1)

    with patch("arr.transmission.process.RpcClient.start", new_callable=AsyncMock) as mock_start:
        resp = client.post("/api/queue/1/resume")
        assert resp.status_code == 200
        mock_start.assert_called_once_with(1)

    with (
        patch(
            "arr.transmission.process.RpcClient.list_torrents",
            new_callable=AsyncMock,
            return_value=[],
        ),
        patch("arr.transmission.process.RpcClient.remove", new_callable=AsyncMock) as mock_remove,
    ):
        resp = client.post("/api/queue/1/delete", json={"confirm": True})
        assert resp.status_code == 200
        mock_remove.assert_called_once_with(1, delete_data=True)


def test_api_download_release(client: TestClient) -> None:
    body = {
        "indexer": "yts",
        "title": "Inception.1080p",
        "infohash": "h123",
        "magnet": "magnet:?xt=urn:btih:h123",
        "media_type": "movie",
        "seeds": 50,
        "size_bytes": 1000,
    }
    with patch(
        "arr.web.routes.queue.enqueue_release", new_callable=AsyncMock, return_value=(True, "added")
    ) as mock_enq:
        resp = client.post("/api/queue/download/release", json=body)
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        mock_enq.assert_called_once()


def test_api_download_magnet(client: TestClient) -> None:
    with patch(
        "arr.web.routes.queue.download_magnet", new_callable=AsyncMock, return_value="ok"
    ) as mock_mag:
        resp = client.post(
            "/api/queue/download/magnet", json={"magnet": "magnet:?xt=urn:btih:xyz"}
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        mock_mag.assert_called_once()


def test_api_series_monitored(client: TestClient, tmp_path: Path) -> None:
    resp = client.get("/api/series")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

    body = {"tmdb_id": 99, "title": "Test Show", "status": "Returning"}
    resp = client.post("/api/series/monitor", json=body)
    assert resp.status_code == 200
    series_id = resp.json()["id"]

    resp = client.get("/api/series")
    assert any(s["title"] == "Test Show" for s in resp.json())

    resp = client.delete(f"/api/series/{series_id}")
    assert resp.status_code == 200


def test_api_config_get_and_put(client: TestClient) -> None:
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert "download_root" in data

    update_payload = {
        "import_mode": "copy",
        "max_concurrent_downloads": 5,
        "prefer_season_packs": False,
    }
    with patch("arr.web.routes.config.save_config") as mock_save:
        resp = client.put("/api/config", json=update_payload)
        assert resp.status_code == 200
        res_data = resp.json()
        assert res_data["status"] == "saved"
        assert res_data["config"]["import_mode"] == "copy"
        assert res_data["config"]["max_concurrent_downloads"] == 5
        mock_save.assert_called_once()


def test_websocket_queue(client: TestClient) -> None:
    t = {
        "id": 1,
        "hashString": "h1",
        "name": "Test",
        "percentDone": 0.5,
        "status": 4,
        "rateDownload": 1000,
        "rateUpload": 0,
        "eta": 10,
        "totalSize": 5000,
    }
    with patch("arr.web.routes.ws._rpc") as mock_rpc_fn:
        mock_rpc = AsyncMock()
        mock_rpc.list_torrents.return_value = [t]
        mock_rpc_fn.return_value = mock_rpc

        with client.websocket_connect("/ws/queue") as websocket:
            data = websocket.receive_json()
            assert "torrents" in data
            assert len(data["torrents"]) == 1
            assert data["torrents"][0]["name"] == "Test"


def test_docker_and_compose_spec_validity() -> None:
    dockerfile = Path("Dockerfile")
    assert dockerfile.exists()
    dockerfile_content = dockerfile.read_text(encoding="utf-8")
    assert "transmission-daemon" in dockerfile_content
    assert "ffmpeg" in dockerfile_content
    assert "ENTRYPOINT" in dockerfile_content

    entrypoint = Path("docker-entrypoint.sh")
    assert entrypoint.exists()
    entrypoint_content = entrypoint.read_text(encoding="utf-8")
    assert "transmission-daemon" in entrypoint_content
    assert "arr web" in entrypoint_content

    compose = Path("docker-compose.yml")
    assert compose.exists()
    compose_content = compose.read_text(encoding="utf-8")
    assert "x-casaos" in compose_content
    assert "/downloads/movies" in compose_content
    assert "/downloads/tv-shows" in compose_content
    assert "/config" in compose_content
    assert "3698" in compose_content


def test_favicon(client: TestClient) -> None:
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers.get("content-type", "")
    assert "<svg" in resp.text


def test_search_movies_annotated_with_library_status(client: TestClient, test_cfg: Config) -> None:
    """R3.2: search results carry availability metadata from the disk library."""
    folder = Path(test_cfg.get("library_root")) / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    (folder / "Inception (2010).mkv").write_bytes(b"x" * 256)

    mock_results = [
        {"id": "tt1375666", "title": "Inception", "year": 2010},
        {"id": "tt0000001", "title": "Some Other Movie", "year": 1999},
    ]
    with patch("arr.metadata.imdb.ImdbClient.search_movies", return_value=mock_results):
        resp = client.get("/api/search/movies?q=Inception")
        assert resp.status_code == 200
        data = resp.json()
    assert data[0]["in_library"] is True
    assert data[0]["library_status"] == "available"
    assert data[1]["in_library"] is False
    assert data[1]["library_status"] is None


def test_search_tv_annotated_with_library_status(client: TestClient, test_cfg: Config) -> None:
    """R3.2: a TV show found on disk is reported as available/monitored."""
    season = Path(test_cfg.get("library_root")) / "tv-shows" / "Breaking Bad (2008)" / "Season 01"
    season.mkdir(parents=True)
    (season / "Breaking Bad - S01E01 - Pilot.mkv").write_bytes(b"x" * 256)

    mock_results = [
        {"id": 1, "title": "Breaking Bad", "name": "Breaking Bad", "year": 2008, "externals": {}}
    ]
    with patch("arr.metadata.tvmaze.TvmazeClient.search_tv_shows", return_value=mock_results):
        resp = client.get("/api/search/tv?q=Breaking+Bad")
        assert resp.status_code == 200
        data = resp.json()
    assert data[0]["in_library"] is True
    assert data[0]["library_status"] in ("available", "partial")
    assert data[0]["available_seasons"] == {"1": [1]}


def test_tv_details_marks_on_disk_episodes_available(client: TestClient, test_cfg: Config) -> None:
    """R3.2: individual episodes already on disk are flagged in the details modal."""
    from arr.core.models import Series

    season_dir = Path(test_cfg.get("library_root")) / "tv-shows" / "Show (2020)" / "Season 01"
    season_dir.mkdir(parents=True)
    (season_dir / "Show - S01E01 - A.mkv").write_bytes(b"x" * 256)

    series = Series(tmdb_id=10, title="Show", year=2020, imdb_id="tt10", status="Ended")
    episodes_payload = [
        {"season": 1, "number": 1, "name": "A", "airdate": "2020-01-01"},
        {"season": 1, "number": 2, "name": "B", "airdate": "2020-01-08"},
    ]
    with (
        patch("arr.metadata.tvmaze.TvmazeClient.tv_details", return_value=series),
        patch("arr.metadata.tvmaze.TvmazeClient._get", return_value=episodes_payload),
    ):
        resp = client.get("/api/tv/10/details")
        assert resp.status_code == 200
        data = resp.json()

    assert data["in_library"] is True
    assert data["library_status"] in ("available", "partial")
    eps = data["seasons"][0]["episodes"]
    assert eps[0]["available"] is True
    assert eps[1]["available"] is False


def test_download_release_warns_when_already_available(
    client: TestClient, test_cfg: Config
) -> None:
    """R3.2: re-downloading an available title requires an explicit confirmation."""
    folder = Path(test_cfg.get("library_root")) / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    (folder / "Inception (2010).mkv").write_bytes(b"x" * 256)

    payload = {
        "indexer": "yts",
        "title": "Inception 2010 1080p",
        "infohash": "h789",
        "magnet": "magnet:?xt=urn:btih:h789",
        "media_type": "movie",
        "display_title": "Inception",
        "year": 2010,
        "seeds": 10,
        "size_bytes": 1000,
    }
    with patch(
        "arr.web.routes.queue.enqueue_release", new_callable=AsyncMock, return_value=(True, "added")
    ) as mock_enq:
        resp = client.post("/api/queue/download/release", json=payload)
        assert resp.status_code == 409
        assert "already" in resp.json()["detail"].lower()
        mock_enq.assert_not_called()

        resp_forced = client.post("/api/queue/download/release", json=dict(payload, force=True))
        assert resp_forced.status_code == 200
        assert resp_forced.json()["status"] == "queued"
        mock_enq.assert_called_once()


def test_download_release_allows_new_movie(client: TestClient) -> None:
    """A title that is not in the library is enqueued without any warning."""
    payload = {
        "indexer": "yts",
        "title": "Brand New Movie 2024 1080p",
        "infohash": "h790",
        "magnet": "magnet:?xt=urn:btih:h790",
        "media_type": "movie",
        "year": 2024,
        "seeds": 10,
        "size_bytes": 1000,
    }
    with patch(
        "arr.web.routes.queue.enqueue_release", new_callable=AsyncMock, return_value=(True, "added")
    ) as mock_enq:
        resp = client.post("/api/queue/download/release", json=payload)
        assert resp.status_code == 200
        mock_enq.assert_called_once()


def test_api_discover_returns_rails_with_availability(
    client: TestClient, test_cfg: Config, tmp_path: Path, monkeypatch
) -> None:
    """R4.1: the Discover homepage is one zero-config call away."""
    folder = Path(test_cfg.get("library_root")) / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    (folder / "Inception (2010).mkv").write_bytes(b"x" * 256)
    monkeypatch.setattr(
        "arr.web.routes.discover._SHOW_ID_MAP_PATH", tmp_path / "imdb_tvmaze_map.json"
    )

    movies = [
        {
            "imdb_id": "tt1375666",
            "title": "Inception",
            "year": 2010,
            "poster": "p.jpg",
            "rating": 8.8,
        }
    ]
    tv = [{"imdb_id": "tt0903747", "title": "Breaking Bad", "year": 2008, "rating": 9.5}]
    with (
        patch("arr.metadata.imdb.ImdbClient.trending_movies", return_value=movies),
        patch("arr.metadata.imdb.ImdbClient.top_rated_movies", return_value=movies),
        patch("arr.metadata.imdb.ImdbClient.trending_tv", return_value=tv),
        patch(
            "arr.metadata.tvmaze.TvmazeClient.search_tv_shows",
            return_value=[{"id": 3, "name": "Breaking Bad", "externals": {"imdb": "tt0903747"}}],
        ),
    ):
        resp = client.get("/api/discover")
        assert resp.status_code == 200
        data = resp.json()

    assert data["trending_movies"][0]["title"] == "Inception"
    assert data["trending_movies"][0]["in_library"] is True
    assert data["trending_movies"][0]["library_status"] == "available"
    assert data["top_rated_movies"][0]["title"] == "Inception"
    assert data["trending_tv"][0]["title"] == "Breaking Bad"
    assert data["trending_tv"][0]["tmdb_id"] == 3
    assert data["spotlight"]["title"] == "Inception"
    assert "Action" in data["genres"]


def test_api_discover_survives_offline_scrapers(client: TestClient) -> None:
    """Blocked scrapers must still render an empty-but-valid Discover page."""
    with (
        patch("arr.metadata.imdb.ImdbClient.trending_movies", return_value=[]),
        patch("arr.metadata.imdb.ImdbClient.top_rated_movies", return_value=[]),
        patch("arr.metadata.imdb.ImdbClient.trending_tv", return_value=[]),
    ):
        resp = client.get("/api/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert data["trending_movies"] == []
    assert data["spotlight"] is None


def test_api_discover_genre(client: TestClient) -> None:
    movies = [{"imdb_id": "tt0468569", "title": "The Dark Knight", "year": 2008}]
    tv = [{"id": 3, "title": "Space Anime", "year": 2022}]
    with patch("arr.metadata.imdb.ImdbClient.movies_by_genre", return_value=movies) as mock_movie:
        resp = client.get("/api/discover/genre?genre=Action&media_type=movie")
        assert resp.status_code == 200
        assert resp.json()["items"][0]["title"] == "The Dark Knight"
        mock_movie.assert_called_once()
    with patch("arr.metadata.tvmaze.TvmazeClient.tv_by_genre", return_value=tv):
        resp = client.get("/api/discover/genre?genre=Anime&media_type=tv")
        assert resp.status_code == 200
        data = resp.json()
    assert data["media_type"] == "tv"
    assert data["items"][0]["title"] == "Space Anime"


def test_api_movie_details_rich(client: TestClient, test_cfg: Config) -> None:
    details = {
        "id": "tt1375666",
        "imdb_id": "tt1375666",
        "title": "Inception",
        "year": 2010,
        "overview": "A thief who steals corporate secrets.",
        "rating": 8.8,
        "genres": ["Action", "Sci-Fi"],
        "runtime": 148,
        "poster": "https://img.example/i.jpg",
        "stars": ["Leonardo DiCaprio"],
        "similar": [
            {"imdb_id": "tt0209144", "title": "Memento", "year": 2000, "poster": "m.jpg"}
        ],
    }
    with patch("arr.metadata.imdb.ImdbClient.movie_details", return_value=details):
        resp = client.get("/api/movie/tt1375666/details")
        assert resp.status_code == 200
        data = resp.json()

    assert data["overview"].startswith("A thief")
    assert data["rating"] == 8.8
    assert data["genres"] == ["Action", "Sci-Fi"]
    assert data["similar"][0]["title"] == "Memento"
    assert data["similar"][0]["in_library"] is False
    assert data["in_library"] is False
    assert data["degraded"] is False


def test_api_movie_details_degrades_when_blocked(client: TestClient) -> None:
    """A blocked IMDb page must not break the detail modal (R4.2)."""
    from arr.metadata.imdb import ImdbError

    with patch("arr.metadata.imdb.ImdbClient.movie_details", side_effect=ImdbError("blocked")):
        resp = client.get("/api/movie/tt1375666/details")
    assert resp.status_code == 200
    data = resp.json()
    assert data["degraded"] is True
    assert data["imdb_id"] == "tt1375666"
    assert data["similar"] == []


def test_tv_details_includes_similar_shows(client: TestClient) -> None:
    from arr.core.models import Series

    series = Series(tmdb_id=10, title="Show", year=2020, imdb_id="tt10", status="Ended")
    summary = {
        "id": 10,
        "title": "Show",
        "year": 2020,
        "rating": 8.1,
        "genres": ["Drama"],
        "poster": "p.jpg",
        "network": "HBO",
        "summary": "A show.",
    }
    similar = [{"id": 11, "title": "Other Show", "year": 2019, "genres": ["Drama"]}]
    with (
        patch("arr.metadata.tvmaze.TvmazeClient.tv_details", return_value=series),
        patch("arr.metadata.tvmaze.TvmazeClient._get", return_value=[]),
        patch("arr.metadata.tvmaze.TvmazeClient.tv_show_summary", return_value=summary),
        patch("arr.metadata.tvmaze.TvmazeClient.similar_shows", return_value=similar),
    ):
        resp = client.get("/api/tv/10/details")
        assert resp.status_code == 200
        data = resp.json()

    assert data["overview"] == "A show."
    assert data["rating"] == 8.1
    assert data["poster"] == "p.jpg"
    assert data["network"] == "HBO"
    assert data["similar"][0]["title"] == "Other Show"


def test_download_release_force_reaches_enqueue(client: TestClient, test_cfg: Config) -> None:
    """CR-02: confirming the duplicate warning must actually enqueue the release."""
    payload = {
        "indexer": "yts",
        "title": "Inception.2010.1080p",
        "infohash": "h999",
        "magnet": "magnet:?xt=urn:btih:h999",
        "media_type": "movie",
        "year": 2010,
        "display_title": "Inception",
        "force": True,
    }
    with patch(
        "arr.web.routes.queue.enqueue_release", new_callable=AsyncMock, return_value=(True, "added")
    ) as mock_enq:
        resp = client.post("/api/queue/download/release", json=payload)

    assert resp.status_code == 200
    assert mock_enq.await_count == 1
    assert mock_enq.await_args.kwargs.get("force") is True


def test_queue_delete_requires_explicit_confirmation(
    client: TestClient, test_cfg: Config
) -> None:
    """CR-03: a blind cross-site POST must not delete files."""
    from arr.pipeline import _db

    hash_ = "c" * 40
    folder = Path(test_cfg.get("library_root")) / "movies" / "Inception (2010)"
    folder.mkdir(parents=True)
    media = folder / "Inception (2010).mkv"
    media.write_bytes(b"x" * 256)
    db = _db(test_cfg)
    db.add_download(hash_, media_type="movie", title="Inception", year=2010, state="queued")
    db.set_download_state(hash_, "imported", destination_path=str(media))
    db.close()

    # No JSON body (what a cross-site HTML form can send) => refused, nothing deleted
    resp = client.post(f"/api/queue/{hash_}/delete")
    assert resp.status_code == 422
    assert media.exists()

    # Explicit confirmation succeeds
    with patch(
        "arr.transmission.process.RpcClient.list_torrents",
        new_callable=AsyncMock,
        return_value=[],
    ):
        resp = client.post(f"/api/queue/{hash_}/delete", json={"confirm": True})
    assert resp.status_code == 200
    assert not media.exists()


def test_priority_up_and_down(client: TestClient) -> None:
    with patch("arr.web.routes.queue._get_rpc") as mock_rpc_fn:
        mock_rpc = AsyncMock()
        mock_rpc.queue_move_up.return_value = {"result": "success"}
        mock_rpc.queue_move_down.return_value = {"result": "success"}
        mock_rpc_fn.return_value = mock_rpc

        resp_up = client.post("/api/queue/42/priority/up")
        assert resp_up.status_code == 200
        assert resp_up.json() == {"status": "moved_up", "id": "42"}
        mock_rpc.queue_move_up.assert_called_once_with(42)

        resp_down = client.post("/api/queue/42/priority/down")
        assert resp_down.status_code == 200
        assert resp_down.json() == {"status": "moved_down", "id": "42"}
        mock_rpc.queue_move_down.assert_called_once_with(42)


def test_download_release_propagates_metadata(client: TestClient) -> None:
    with patch("arr.web.routes.queue.enqueue_release", new_callable=AsyncMock) as mock_enq:
        mock_enq.return_value = (True, "Queued successfully")
        payload = {
            "indexer": "yts",
            "title": "Inception.2010.1080p",
            "infohash": "hash123",
            "magnet": "magnet:?xt=urn:btih:hash123",
            "media_type": "movie",
            "seeds": 50,
            "peers": 10,
            "size_bytes": 2000000000,
            "imdb_id": "tt1375666",
            "tmdb_id": 27205,
        }
        resp = client.post("/api/queue/download/release", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        mock_enq.assert_called_once()
        _, kwargs = mock_enq.call_args
        assert kwargs["imdb_id"] == "tt1375666"
        assert kwargs["tmdb_id"] == 27205


def test_download_release_with_imdb_id_in_tmdb_field(client: TestClient) -> None:
    with patch(
        "arr.web.routes.queue.enqueue_release", new_callable=AsyncMock, return_value=(True, "added")
    ) as mock_enq:
        payload = {
            "indexer": "yts",
            "title": "Movie.2020.1080p",
            "infohash": "hash_tt",
            "magnet": "magnet:?xt=urn:btih:hash_tt",
            "media_type": "movie",
            "size_bytes": 1500000000,
            "tmdb_id": "tt1302011",  # Passed string IMDb ID in tmdb_id field
        }
        resp = client.post("/api/queue/download/release", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"
        mock_enq.assert_called_once()
        _, kwargs = mock_enq.call_args
        assert kwargs["imdb_id"] == "tt1302011"
        assert kwargs["tmdb_id"] is None


def test_update_config_subtitle_fields(client: TestClient) -> None:
    payload = {
        "subtitles_enabled": False,
        "subtitles_forced_only": True,
        "subtitle_languages": ["es", "fr"],
    }
    with patch("arr.web.routes.config.save_config"):
        resp = client.put("/api/config", json=payload)
        assert resp.status_code == 200
        cfg = resp.json()["config"]
        assert cfg["subtitles_enabled"] is False
        assert cfg["subtitles_forced_only"] is True
        assert cfg["subtitle_languages"] == ["es", "fr"]


def test_spa_fallback_missing_build_diagnostic(test_cfg: Config, tmp_path: Path) -> None:
    """An unbuilt frontend bundle must yield a build hint, not a crash."""
    unbuilt = tmp_path / "unbuilt-dist"
    with patch("arr.web.app.DIST_DIR", unbuilt):
        client = TestClient(create_app(test_cfg))
        resp = client.get("/queue")
        assert resp.status_code == 200
        assert "Onyx frontend bundle is missing" in resp.text
        assert "npm run build" in resp.text
        assert "doctype" in resp.text.lower()
        api = client.get("/api/config")
        assert api.status_code == 200
        assert api.json()["library_root"] == str(test_cfg.get("library_root"))


def test_web_startup_runs_library_maintenance(test_cfg: Config) -> None:
    """IM-05: app startup must normalise the library and index disk media (R2.3/R3.1)."""
    import arr.pipeline as pipeline

    app = create_app(test_cfg)
    calls: list[str] = []
    with (
        patch(
            "arr.pipeline.cleanup_duplicate_folders",
            side_effect=lambda *a, **k: calls.append("cleanup") or 0,
        ),
        patch(
            "arr.pipeline.sync_disk_library",
            side_effect=lambda *a, **k: calls.append("sync")
            or {"movies": 0, "shows": 0, "episodes": 0, "monitored": 0},
        ),
        TestClient(app) as client,
    ):
        assert client.get("/").status_code == 200

    assert "cleanup" in calls
    assert "sync" in calls
    assert pipeline is not None


def test_index_page_spa_theme_tokens(client: TestClient) -> None:
    """R5.1: the served stylesheet carries the obsidian/indigo palette."""
    html = client.get("/").text
    stylesheets = re.findall(r'href="(/assets/[^"]+\.css)"', html)
    if not stylesheets:
        pytest.skip("frontend bundle not built: cd frontend && npm run build")
    css = client.get(stylesheets[0]).text
    for token in ("#090d16", "#111827", "#6366f1"):
        assert token in css


def test_download_release_propagates_enqueue_failure(client: TestClient) -> None:
    with patch(
        "arr.web.routes.queue.enqueue_release",
        new_callable=AsyncMock,
        return_value=(False, "Transmission unavailable: connection refused on port 9091"),
    ):
        payload = {
            "indexer": "yts",
            "title": "Movie.Fail.1080p",
            "infohash": "hash_fail",
            "magnet": "magnet:?xt=urn:btih:hash_fail",
            "media_type": "movie",
        }
        resp = client.post("/api/queue/download/release", json=payload)
        assert resp.status_code == 500
        assert "Transmission unavailable" in resp.json()["detail"]


def test_get_queue_merges_sqlite_and_transmission(client: TestClient, test_cfg: Config) -> None:
    from arr.pipeline import _db

    db = _db(test_cfg)
    try:
        db.add_download(
            "hash_sqlite_only",
            media_type="movie",
            title="Inception SQLite",
            state="queued",
        )
        db.add_download(
            "hash_both",
            media_type="tv",
            title="Show Both",
            state="downloading",
        )
    finally:
        db.close()

    mock_torrents = [
        {
            "id": 42,
            "hashString": "hash_both",
            "name": "Show Live Transmission",
            "percentDone": 0.45,
            "status": 4,
            "rateDownload": 2500000,
            "rateUpload": 50000,
            "eta": 120,
            "totalSize": 1000000000,
        }
    ]

    with patch(
        "arr.transmission.process.RpcClient.list_torrents", new_callable=AsyncMock
    ) as m_list:
        m_list.return_value = mock_torrents
        resp = client.get("/api/queue")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 2

        by_hash = {it["infohash"]: it for it in items}
        assert "hash_sqlite_only" in by_hash
        assert by_hash["hash_sqlite_only"]["status"] == "Queued"
        assert by_hash["hash_sqlite_only"]["progress"] == 0.0

        assert "hash_both" in by_hash
        assert by_hash["hash_both"]["id"] == 42
        assert by_hash["hash_both"]["name"] == "Show Live Transmission"
        assert by_hash["hash_both"]["progress"] == 45.0
        assert by_hash["hash_both"]["rate_download"] == 2500000


def test_queue_actions_accept_infohash_string(client: TestClient) -> None:
    hash_str = "abcdef1234567890abcdef1234567890abcdef12"
    with (
        patch("arr.transmission.process.RpcClient.stop", new_callable=AsyncMock) as m_stop,
        patch("arr.transmission.process.RpcClient.start", new_callable=AsyncMock) as m_start,
        patch("arr.transmission.process.RpcClient.remove", new_callable=AsyncMock) as m_remove,
        patch(
            "arr.transmission.process.RpcClient.queue_move_up", new_callable=AsyncMock
        ) as m_up,
        patch(
            "arr.transmission.process.RpcClient.queue_move_down", new_callable=AsyncMock
        ) as m_down,
    ):

        # Pause with hash string
        resp = client.post(f"/api/queue/{hash_str}/pause")
        assert resp.status_code == 200
        m_stop.assert_called_with(hash_str)

        # Resume with hash string
        resp = client.post(f"/api/queue/{hash_str}/resume")
        assert resp.status_code == 200
        m_start.assert_called_with(hash_str)

        # Priority up with hash string
        resp = client.post(f"/api/queue/{hash_str}/priority/up")
        assert resp.status_code == 200
        m_up.assert_called_with(hash_str)

        # Priority down with hash string
        resp = client.post(f"/api/queue/{hash_str}/priority/down")
        assert resp.status_code == 200
        m_down.assert_called_with(hash_str)

        # Delete with hash string
        with patch(
            "arr.transmission.process.RpcClient.list_torrents",
            new_callable=AsyncMock,
            return_value=[],
        ):
            resp = client.post(f"/api/queue/{hash_str}/delete", json={"confirm": True})
            assert resp.status_code == 200
        m_remove.assert_called_with(hash_str, delete_data=True)


