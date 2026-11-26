"""Endless Discover browsing: YTS movie pages and TVMaze show pages."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx
from starlette.testclient import TestClient

from arr.config.settings import DEFAULTS, Config
from arr.metadata.tvmaze import TvmazeClient
from arr.metadata.yts import YtsCatalog, YtsError
from arr.web.app import create_app

YTS = "https://yts.test"
TVMAZE = "https://api.tvmaze.test"


def make_cfg(tmp_path: Path) -> Config:
    return Config(
        values=dict(
            DEFAULTS,
            yts_base_url=YTS,
            tvmaze_base_url=TVMAZE,
            download_root=str(tmp_path / "downloads"),
            library_root=str(tmp_path / "downloads"),
        )
    )


YTS_PAGE = {
    "status": "ok",
    "data": {
        "movie_count": 45,
        "limit": 20,
        "page_number": 2,
        "movies": [
            {
                "id": 77,
                "imdb_code": "tt0816692",
                "title": "Interstellar",
                "year": 2014,
                "rating": 8.7,
                "genres": ["Adventure", "Drama", "Sci-Fi"],
                "summary": "A team travels through a wormhole.",
                "medium_cover_image": "https://img.yts.test/interstellar.jpg",
                "large_cover_image": "https://img.yts.test/interstellar-large.jpg",
            }
        ],
    },
}

SHOWS = [
    {
        "id": 1,
        "name": "Quiet Drama",
        "type": "Scripted",
        "genres": ["Drama"],
        "weight": 10,
        "rating": {"average": 7.1},
        "image": None,
        "externals": {},
        "summary": "",
    },
    {
        "id": 2,
        "name": "Loud Comedy",
        "type": "Scripted",
        "genres": ["Comedy"],
        "weight": 90,
        "rating": {"average": 6.5},
        "image": None,
        "externals": {},
        "summary": "",
    },
    {
        "id": 3,
        "name": "Space Show",
        "type": "Scripted",
        "genres": ["Science-Fiction"],
        "weight": 50,
        "rating": {"average": 8.4},
        "image": None,
        "externals": {},
        "summary": "",
    },
]


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


def test_yts_browse_maps_movies_and_asks_for_popular_pages(tmp_path: Path) -> None:
    with respx.mock:
        route = respx.get(f"{YTS}/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, json=YTS_PAGE)
        )
        items, total = YtsCatalog(make_cfg(tmp_path), cache_dir=tmp_path).browse(
            genre="Sci-Fi", page=2, limit=20
        )

    params = route.calls.last.request.url.params
    assert params["genre"] == "Sci-Fi"
    assert params["page"] == "2"
    assert params["sort_by"] == "download_count"
    assert total == 45
    assert items == [
        {
            "id": "tt0816692",
            "imdb_id": "tt0816692",
            "title": "Interstellar",
            "year": 2014,
            "rating": 8.7,
            "poster": "https://img.yts.test/interstellar.jpg",
            "genres": ["Adventure", "Drama", "Sci-Fi"],
            "overview": "A team travels through a wormhole.",
            "media_type": "movie",
            "source": "YTS",
        }
    ]


def test_yts_browse_follows_the_mirror_redirect(tmp_path: Path) -> None:
    """yts.lt answers with a 301 to a live mirror; discovery has to follow it."""
    mirror = "https://yts.mirror.test"
    with respx.mock:
        respx.get(f"{YTS}/api/v2/list_movies.json").mock(
            return_value=httpx.Response(
                301, headers={"Location": f"{mirror}/api/v2/list_movies.json"}
            )
        )
        respx.get(f"{mirror}/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, json=YTS_PAGE)
        )
        items, total = YtsCatalog(make_cfg(tmp_path), cache_dir=tmp_path).browse(
            genre=None, page=2
        )
    assert total == 45
    assert items[0]["title"] == "Interstellar"


def test_yts_browse_treats_a_missing_movies_key_as_an_empty_page(tmp_path: Path) -> None:
    body = {"status": "ok", "data": {"movie_count": 0, "limit": 20, "page_number": 1}}
    with respx.mock:
        respx.get(f"{YTS}/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, json=body)
        )
        items, total = YtsCatalog(make_cfg(tmp_path), cache_dir=tmp_path).browse(
            genre=None, page=1
        )
    assert items == []
    assert total == 0


def test_yts_browse_serves_repeat_pages_from_the_cache(tmp_path: Path) -> None:
    with respx.mock:
        route = respx.get(f"{YTS}/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, json=YTS_PAGE)
        )
        catalog = YtsCatalog(make_cfg(tmp_path), cache_dir=tmp_path)
        catalog.browse(genre="Sci-Fi", page=2, limit=20)
        catalog.browse(genre="Sci-Fi", page=2, limit=20)
    assert route.call_count == 1


def test_yts_browse_raises_when_unreachable_and_nothing_is_cached(tmp_path: Path) -> None:
    with respx.mock:
        respx.get(f"{YTS}/api/v2/list_movies.json").mock(return_value=httpx.Response(500))
        with pytest.raises(YtsError):
            YtsCatalog(make_cfg(tmp_path), cache_dir=tmp_path).browse(genre=None, page=1)


def test_tv_browse_pages_through_the_popularity_ranked_catalogue(tmp_path: Path) -> None:
    with respx.mock:
        respx.get(f"{TVMAZE}/shows").mock(return_value=httpx.Response(200, json=SHOWS))
        client = TvmazeClient(make_cfg(tmp_path), cache_dir=tmp_path)
        first, total = client.browse_tv(None, page=1, limit=2)
        second, _ = client.browse_tv(None, page=2, limit=2)
        beyond, _ = client.browse_tv(None, page=9, limit=2)

    assert total == 3
    assert [s["id"] for s in first] == [2, 3]
    assert [s["id"] for s in second] == [1]
    assert beyond == []


def test_tv_browse_filters_by_genre_before_paging(tmp_path: Path) -> None:
    with respx.mock:
        respx.get(f"{TVMAZE}/shows").mock(return_value=httpx.Response(200, json=SHOWS))
        client = TvmazeClient(make_cfg(tmp_path), cache_dir=tmp_path)
        items, total = client.browse_tv("Sci-Fi", page=1, limit=10)

    assert total == 1
    assert [s["title"] for s in items] == ["Space Show"]


def test_discover_browse_returns_an_annotated_page_with_has_more(
    client: TestClient,
) -> None:
    with patch("arr.metadata.yts.YtsCatalog.browse", return_value=([_movie()], 45)) as browse:
        resp = client.get("/api/discover/browse?media_type=movie&genre=Sci-Fi&page=2")
    assert resp.status_code == 200
    data = resp.json()
    assert data["media_type"] == "movie"
    assert data["genre"] == "Sci-Fi"
    assert data["page"] == 2
    assert data["has_more"] is True  # 2 pages of 20 cover 40 of 45 titles
    assert data["items"][0]["title"] == "Interstellar"
    assert data["items"][0]["in_library"] is False
    assert browse.call_args.kwargs == {"genre": "Sci-Fi", "page": 2, "limit": 20}


def test_discover_browse_last_page_has_no_more(client: TestClient) -> None:
    with patch("arr.metadata.yts.YtsCatalog.browse", return_value=([_movie()], 21)):
        data = client.get("/api/discover/browse?media_type=movie&page=2").json()
    assert data["has_more"] is False


def test_discover_browse_empty_page_never_asks_for_more(client: TestClient) -> None:
    with patch("arr.metadata.yts.YtsCatalog.browse", return_value=([], 0)):
        data = client.get("/api/discover/browse?media_type=movie&genre=Anime").json()
    assert data["items"] == []
    assert data["has_more"] is False


def test_discover_browse_serves_shows_from_tvmaze(client: TestClient) -> None:
    show = {"id": 3, "title": "Space Show", "year": 2020, "media_type": "tv", "genres": []}
    with patch("arr.metadata.tvmaze.TvmazeClient.browse_tv", return_value=([show], 1)) as browse:
        data = client.get("/api/discover/browse?media_type=tv&genre=Sci-Fi&page=1").json()
    assert data["media_type"] == "tv"
    assert data["has_more"] is False
    assert data["items"][0]["title"] == "Space Show"
    assert browse.call_args.args == ("Sci-Fi", 1, 20)


def test_discover_browse_marks_titles_already_on_disk(client: TestClient, test_cfg: Config) -> None:
    folder = Path(str(test_cfg.get("library_root"))) / "movies" / "Interstellar (2014)"
    folder.mkdir(parents=True)
    (folder / "Interstellar (2014).mkv").write_bytes(b"x" * 256)

    with patch("arr.metadata.yts.YtsCatalog.browse", return_value=([_movie()], 1)):
        data = client.get("/api/discover/browse?media_type=movie").json()

    assert data["items"][0]["in_library"] is True
    assert data["items"][0]["library_status"] == "available"


def test_discover_browse_reports_an_unreachable_catalogue(client: TestClient) -> None:
    with patch("arr.metadata.yts.YtsCatalog.browse", side_effect=YtsError("down")):
        resp = client.get("/api/discover/browse?media_type=movie")
    assert resp.status_code == 502
    assert "Could not load titles" in resp.json()["detail"]


def test_discover_homepage_lists_genres_per_media_type(client: TestClient) -> None:
    with (
        patch("arr.metadata.imdb.ImdbClient.trending_movies", return_value=[]),
        patch("arr.metadata.imdb.ImdbClient.top_rated_movies", return_value=[]),
        patch("arr.metadata.imdb.ImdbClient.trending_tv", return_value=[]),
    ):
        data = client.get("/api/discover").json()

    by_type = data["genres_by_type"]
    assert "Anime" in by_type["tv"]
    assert "Animation" in by_type["tv"]
    assert "Anime" not in by_type["movie"]
    assert "Sci-Fi" in by_type["movie"] and "Sci-Fi" in by_type["tv"]


def _movie() -> dict:
    return {
        "id": "tt0816692",
        "imdb_id": "tt0816692",
        "title": "Interstellar",
        "year": 2014,
        "rating": 8.7,
        "poster": "https://img.yts.test/interstellar.jpg",
        "genres": ["Sci-Fi"],
        "media_type": "movie",
    }
