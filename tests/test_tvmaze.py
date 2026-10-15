import httpx
import respx

from arr.config.settings import DEFAULTS, Config
from arr.metadata.tvmaze import TvmazeClient

BASE = "https://api.tvmaze.com"


def cfg():
    return Config(values=dict(DEFAULTS, tvmaze_base_url=BASE))


def test_search_tv_maps_show(tmp_path):
    payload = [
        {
            "score": 1.0,
            "show": {
                "id": 5,
                "name": "Show",
                "status": "Returning Series",
                "premiered": "2020-01-01",
                "externals": {"imdb": "tt5", "thetvdb": 42},
            },
        }
    ]
    with respx.mock:
        respx.get(f"{BASE}/search/shows").mock(return_value=httpx.Response(200, json=payload))
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        s = c.search_tv("show")
    assert s and s["id"] == 5
    assert s["name"] == "Show"
    assert s["externals"]["imdb"] == "tt5"


def test_search_tv_no_results(tmp_path):
    with respx.mock:
        respx.get(f"{BASE}/search/shows").mock(return_value=httpx.Response(200, json=[]))
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        assert c.search_tv("zzz") is None


def test_full_series_maps_seasons_and_externals(tmp_path):
    details = {
        "id": 5,
        "name": "Show",
        "status": "Returning Series",
        "premiered": "2020-01-01",
        "externals": {"imdb": "tt5"},
    }
    episodes = [
        {"season": 1, "number": 1, "name": "Pilot", "airdate": "2020-01-02"},
        {"season": 1, "number": 2, "name": "Two", "airdate": "2020-01-09"},
        {"season": 2, "number": 1, "name": "S2E1", "airdate": "2021-01-01"},
        {"season": 0, "number": 1, "name": "Special", "airdate": "2019-12-01"},
    ]
    with respx.mock:
        respx.get(f"{BASE}/shows/5").mock(return_value=httpx.Response(200, json=details))
        respx.get(f"{BASE}/shows/5/episodes").mock(
            return_value=httpx.Response(200, json=episodes)
        )
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        s = c.full_series(5)
    assert s.title == "Show"
    assert s.year == 2020
    assert s.imdb_id == "tt5"
    assert s.status == "Returning Series"
    assert [season.season_number for season in s.seasons] == [1, 2]
    assert s.seasons[0].episodes[1].name == "Two"


def test_cache_hit_avoids_second_network_call(tmp_path):
    payload = [
        {
            "show": {
                "id": 9,
                "name": "X",
                "status": "Ended",
                "premiered": "2010-01-01",
                "externals": {},
            }
        }
    ]
    with respx.mock:
        route = respx.get(f"{BASE}/search/shows").mock(
            return_value=httpx.Response(200, json=payload)
        )
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        c.search_tv("x")
        c.search_tv("x")
    assert route.call_count == 1


def test_search_tv_shows_multiple_results(tmp_path):
    payload = [
        {
            "show": {
                "id": 1,
                "name": "Frieren: Beyond Journey's End",
                "status": "Ended",
                "premiered": "2023-09-29",
                "genres": ["Animation", "Adventure", "Fantasy"],
                "network": {"name": "Nippon TV"},
                "externals": {"imdb": "tt22248374"},
            }
        },
        {
            "show": {
                "id": 2,
                "name": "Frieren: Special",
                "status": "Ended",
                "premiered": "2024-01-01",
                "genres": ["Animation"],
                "webChannel": {"name": "YouTube"},
                "externals": {},
            }
        },
    ]
    with respx.mock:
        respx.get(f"{BASE}/search/shows").mock(return_value=httpx.Response(200, json=payload))
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        shows = c.search_tv_shows("frieren")
    assert len(shows) == 2
    assert shows[0]["id"] == 1
    assert shows[0]["name"] == "Frieren: Beyond Journey's End"
    assert shows[0]["network"] == "Nippon TV"
    assert shows[1]["id"] == 2
    assert shows[1]["network"] == "YouTube"


def test_seasons_overview_status_calculation(tmp_path):
    details = {
        "id": 10,
        "name": "Test Show",
        "status": "Running",
        "premiered": "2023-01-01",
        "externals": {},
    }
    episodes = [
        {"season": 1, "number": 1, "name": "E1", "airdate": "2023-01-01"},
        {"season": 1, "number": 2, "name": "E2", "airdate": "2023-01-08"},
        {"season": 2, "number": 1, "name": "E3", "airdate": "2030-01-01"},
        {"season": 3, "number": 1, "name": "E4", "airdate": "2030-06-01"},
    ]
    with respx.mock:
        respx.get(f"{BASE}/shows/10").mock(return_value=httpx.Response(200, json=details))
        respx.get(f"{BASE}/shows/10/episodes").mock(
            return_value=httpx.Response(200, json=episodes)
        )
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        seasons = c.seasons_overview(10)
    assert len(seasons) == 3
    # Season 1 past dates -> Completed
    assert seasons[0]["season_number"] == 1
    assert seasons[0]["status"] == "Completed"
    assert seasons[0]["episode_count"] == 2
    assert seasons[0]["premiere_date"] == "2023-01-01"
    assert seasons[0]["end_date"] == "2023-01-08"
    # Season 2 future dates -> Upcoming
    assert seasons[1]["season_number"] == 2
    assert seasons[1]["status"] == "Upcoming"
    assert seasons[1]["episode_count"] == 1


# ------------------- TVMaze discovery (R4.1/R4.2) -------------------

CATALOG = [
    {
        "id": 1,
        "name": "Quiet Drama",
        "status": "Ended",
        "premiered": "2001-01-01",
        "genres": ["Drama"],
        "weight": 10,
        "rating": {"average": 9.9},
        "image": {"medium": "https://img.example/quiet.jpg"},
        "externals": {"imdb": "tt1"},
        "summary": "<p>A quiet drama.</p>",
        "network": {"name": "HBO"},
    },
    {
        "id": 2,
        "name": "Loud Comedy",
        "status": "Running",
        "premiered": "2019-05-05",
        "genres": ["Comedy", "Drama"],
        "weight": 99,
        "rating": {"average": 6.5},
        "image": {"medium": "https://img.example/loud.jpg"},
        "externals": {"imdb": "tt2"},
        "summary": "<p>A loud comedy.</p>",
        "webChannel": {"name": "Netflix"},
    },
    {
        "id": 3,
        "name": "Space Anime",
        "status": "Running",
        "premiered": "2022-02-02",
        "genres": ["Anime", "Science-Fiction"],
        "weight": 40,
        "rating": {"average": 8.4},
        "image": {"medium": "https://img.example/space.jpg"},
        "externals": {"imdb": "tt3"},
        "summary": "<p>Space.</p>",
        "network": {"name": "Crunchyroll"},
    },
    {
        "id": 4,
        "name": "Another Quiet Drama",
        "status": "Ended",
        "premiered": "1998-03-03",
        "genres": ["Drama"],
        "weight": 5,
        "rating": {"average": 7.1},
        "image": {"medium": "https://img.example/another.jpg"},
        "externals": {"imdb": "tt4"},
        "summary": "<p>Another drama.</p>",
        "network": {"name": "BBC"},
    },
]


def test_trending_tv_ranks_cached_catalog_by_weight(tmp_path):
    with respx.mock:
        respx.get(f"{BASE}/shows").mock(return_value=httpx.Response(200, json=CATALOG))
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        items = c.trending_tv(limit=3)

    assert [i["id"] for i in items] == [2, 3, 1]  # weight desc
    assert items[0]["title"] == "Loud Comedy"
    assert items[0]["poster"] == "https://img.example/loud.jpg"
    assert items[0]["rating"] == 6.5
    assert items[0]["media_type"] == "tv"


def test_tv_catalog_is_cached_between_calls(tmp_path):
    with respx.mock:
        route = respx.get(f"{BASE}/shows").mock(
            return_value=httpx.Response(200, json=CATALOG)
        )
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        c.trending_tv(limit=2)
        first_calls = route.call_count
        c.tv_by_genre("Drama", limit=2)
        second_calls = route.call_count

    assert first_calls >= 1
    assert second_calls == first_calls  # second use is served from the disk cache


def test_tv_by_genre_filters_and_ranks(tmp_path):
    with respx.mock:
        respx.get(f"{BASE}/shows").mock(return_value=httpx.Response(200, json=CATALOG))
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        items = c.tv_by_genre("Drama", limit=2)

    assert [i["id"] for i in items] == [2, 1]
    assert all("Drama" in i["genres"] for i in items)


def test_similar_shows_prefers_shared_genres(tmp_path):
    with respx.mock:
        respx.get(f"{BASE}/shows").mock(return_value=httpx.Response(200, json=CATALOG))
        respx.get(f"{BASE}/shows/2").mock(
            return_value=httpx.Response(200, json=CATALOG[1])
        )
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        items = c.similar_shows(2, limit=4)

    ids = [i["id"] for i in items]
    assert 2 not in ids
    # only the two dramas share a genre with "Loud Comedy", ranked by weight
    assert ids == [1, 4]
    assert items[0]["title"] == "Quiet Drama"


def test_trending_tv_returns_empty_when_catalog_unavailable(tmp_path):
    with respx.mock:
        respx.get(f"{BASE}/shows").mock(return_value=httpx.Response(503, text="down"))
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        assert c.trending_tv(limit=5) == []
        assert c.tv_by_genre("Drama", limit=5) == []


def test_tv_details_includes_summary_and_genres(tmp_path):
    with respx.mock:
        respx.get(f"{BASE}/shows/3").mock(return_value=httpx.Response(200, json=CATALOG[2]))
        c = TvmazeClient(cfg(), cache_dir=tmp_path)
        d = c.tv_show_summary(3)

    assert d["title"] == "Space Anime"
    assert d["genres"] == ["Anime", "Science-Fiction"]
    assert d["rating"] == 8.4
    assert d["network"] == "Crunchyroll"

