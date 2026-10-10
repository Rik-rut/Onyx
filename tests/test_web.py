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
        "arr.web.routes.queue.enqueue_release", new_callable=AsyncMock, return_value="added"
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
