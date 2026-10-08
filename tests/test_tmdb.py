import httpx
import respx

from arr.config.settings import DEFAULTS, Config
from arr.metadata.tmdb import TmdbClient

BASE = "https://api.themoviedb.org/3"


def cfg():
    return Config(values=dict(DEFAULTS, tmdb_api_key="k", tmdb_base_url=BASE))


def test_search_movie(tmp_path):
    payload = {"results": [{"id": 1, "title": "Inception"}]}
    with respx.mock:
        respx.get(f"{BASE}/search/movie").mock(
            return_value=httpx.Response(200, json=payload)
        )
        c = TmdbClient(cfg(), cache_dir=tmp_path)
        m = c.search_movie("inception")
    assert m and m["id"] == 1


def test_full_series_uses_short_ttl_for_returning(tmp_path):
    details = {
        "id": 5,
        "name": "Show",
        "status": "Returning Series",
        "first_air_date": "2020-01-01",
        "seasons": [{"season_number": 1}],
    }
    season = {
        "episodes": [{"episode_number": 1, "name": "Pilot", "air_date": "2020-01-02"}]
    }
    with respx.mock:
        respx.get(f"{BASE}/tv/5").mock(return_value=httpx.Response(200, json=details))
        respx.get(f"{BASE}/tv/5/external_ids").mock(
            return_value=httpx.Response(200, json={"imdb_id": "tt5"})
        )
        respx.get(f"{BASE}/tv/5/season/1").mock(
            return_value=httpx.Response(200, json=season)
        )
        c = TmdbClient(cfg(), cache_dir=tmp_path)
        s = c.full_series(5)
    assert s.status == "Returning Series"
    assert s.imdb_id == "tt5"
    assert s.seasons[0].episodes[0].name == "Pilot"


def test_cache_hit_avoids_network(tmp_path):
    payload = {"results": [{"id": 9}]}
    with respx.mock:
        route = respx.get(f"{BASE}/search/movie").mock(
            return_value=httpx.Response(200, json=payload)
        )
        c = TmdbClient(cfg(), cache_dir=tmp_path)
        c.search_movie("x")
        c.search_movie("x")
    assert route.call_count == 1
