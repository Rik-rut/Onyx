from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient

from arr.config.settings import DEFAULTS, Config
from arr.core.models import MediaType, Release
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


def test_index_page(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ARR" in resp.text
    assert "Shows & Movies Downloader" in resp.text


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

    with patch("arr.transmission.process.RpcClient.remove", new_callable=AsyncMock) as mock_remove:
        resp = client.post("/api/queue/1/delete")
        assert resp.status_code == 200
        mock_remove.assert_called_once_with(1, delete_data=False)


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
    assert "8080" in compose_content


def test_favicon(client: TestClient) -> None:
    resp = client.get("/favicon.ico")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers.get("content-type", "")
    assert "<svg" in resp.text


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


def test_index_page_phase6_elements(client: TestClient) -> None:
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Rescan Library" in resp.text
    assert "tvDetails" in resp.text
    assert "priorityUp" in resp.text
    assert "priorityDown" in resp.text
    assert "filteredReleases" in resp.text
    assert "subtitleLanguagesInput" in resp.text


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
        resp = client.post(f"/api/queue/{hash_str}/delete")
        assert resp.status_code == 200
        m_remove.assert_called_with(hash_str, delete_data=False)


