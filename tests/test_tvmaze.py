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
