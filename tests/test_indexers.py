import asyncio

import httpx
import pytest
import respx

from arr.config.settings import DEFAULTS, Config
from arr.core.models import MediaType, Query
from arr.indexers import EztvAdapter, HttpClient, NyaaAdapter, SchemaMismatchError, YtsAdapter


def cfg():
    return Config(values=dict(DEFAULTS))


def http():
    return HttpClient(cfg())


def test_yts_search():
    payload = {
        "data": {
            "movies": [
                {
                    "id": 1,
                    "title": "Inception",
                    "year": 2010,
                    "torrents": [
                        {
                            "hash": "ABC123",
                            "quality": "1080p",
                            "type": "bluray",
                            "size_bytes": 2000000000,
                            "seeds": 100,
                            "peers": 10,
                        }
                    ],
                }
            ]
        }
    }
    with respx.mock:
        respx.get("https://yts.mx/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        out = asyncio.run(
            YtsAdapter("https://yts.mx", http()).search(
                Query(media_type=MediaType.MOVIE, text="inception")
            )
        )
    assert len(out) == 1
    assert out[0].infohash == "abc123"
    assert out[0].seeds == 100
    assert out[0].magnet.startswith("magnet:?xt=urn:btih:abc123")
    assert "&dn=Inception" in out[0].magnet
    assert "&tr=udp" in out[0].magnet


def test_tracker_list_custom_and_default():
    from arr.indexers.base import DEFAULT_PUBLIC_TRACKERS, tracker_list

    # Default
    assert tracker_list({}) == DEFAULT_PUBLIC_TRACKERS
    assert tracker_list(None) == DEFAULT_PUBLIC_TRACKERS

    # Custom
    custom_cfg = {"trackers": ["udp://custom.tracker:6969/announce"]}
    assert tracker_list(custom_cfg) == ["udp://custom.tracker:6969/announce"]


def test_yts_search_with_imdb_id_and_year_filter(tmp_path):
    payload = {
        "data": {
            "movies": [
                {
                    "id": 1,
                    "title": "Spider-Man",
                    "year": 2002,
                    "imdb_code": "tt0145487",
                    "torrents": [
                        {
                            "hash": "HASH2002",
                            "quality": "1080p",
                            "type": "bluray",
                            "size_bytes": 2000000000,
                            "seeds": 100,
                            "peers": 10,
                        }
                    ],
                },
                {
                    "id": 2,
                    "title": "Spider-Man: Brand New Day",
                    "year": 2026,
                    "imdb_code": "tt9999999",
                    "torrents": [
                        {
                            "hash": "HASH2026",
                            "quality": "1080p",
                            "type": "bluray",
                            "size_bytes": 2000000000,
                            "seeds": 100,
                            "peers": 10,
                        }
                    ],
                },
            ]
        }
    }
    with respx.mock:
        route = respx.get("https://yts.mx/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        out = asyncio.run(
            YtsAdapter("https://yts.mx", HttpClient(cfg(), cache_dir=tmp_path)).search(
                Query(
                    media_type=MediaType.MOVIE,
                    text="Spider-Man",
                    year=2002,
                    imdb_id="tt0145487",
                )
            )
        )
    assert route.called
    assert route.calls.last.request.url.params["query_term"] == "tt0145487"
    assert len(out) == 1
    assert out[0].year == 2002
    assert "2002" in out[0].title


def test_yts_schema_mismatch():
    with respx.mock:
        respx.get("https://yts.mx/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, text="<html>")
        )
        with pytest.raises(SchemaMismatchError):
            asyncio.run(
                YtsAdapter("https://yts.mx", http()).search(
                    Query(media_type=MediaType.MOVIE, text="x")
                )
            )


def test_yts_empty_results_is_not_schema_mismatch():
    """A successful query with no matches omits `movies`; must return [] not raise."""
    payload = {
        "status": "ok",
        "data": {"movie_count": 0, "limit": 20, "page_number": 1},
    }
    with respx.mock:
        respx.get("https://yts.mx/api/v2/list_movies.json").mock(
            return_value=httpx.Response(200, json=payload)
        )
        out = asyncio.run(
            YtsAdapter("https://yts.mx", http()).search(
                Query(media_type=MediaType.MOVIE, text="nothing")
            )
        )
    assert out == []


def test_eztv_search():
    payload = {
        "torrents": [
            {
                "title": "Show.S01E01.1080p",
                "magnet_url": "magnet:?xt=urn:btih:DEADBEEF&dn=x",
                "seeds": 5,
                "peers": 1,
                "size_bytes": "1000000",
                "season": "1",
                "episode": "1",
                "imdb_id": "123",
            }
        ]
    }
    with respx.mock:
        respx.get("https://eztv.re/api/get-torrents").mock(
            return_value=httpx.Response(200, json=payload)
        )
        out = asyncio.run(
            EztvAdapter("https://eztv.re", http()).search(
                Query(media_type=MediaType.TV, text="show", imdb_id="tt123")
            )
        )
    assert len(out) == 1
    assert out[0].season == 1
    assert out[0].episode == 1
    assert out[0].infohash == "deadbeef"


NYAA_RSS = """<?xml version="1.0"?>
<rss version="2.0" xmlns:nyaa="https://nyaa.si/xmlns/nyaa"><channel>
<item><title>[SubsPlease] Anime - 01 (1080p)</title><link>magnet:?xt=urn:btih:CAFE1234</link>
<nyaa:seeders>42</nyaa:seeders><nyaa:leechers>3</nyaa:leechers><nyaa:size>1.2 GiB</nyaa:size>
<nyaa:infoHash>CAFE1234</nyaa:infoHash></item>
</channel></rss>"""


def test_nyaa_search():
    with respx.mock:
        respx.get("https://nyaa.si/").mock(return_value=httpx.Response(200, text=NYAA_RSS))
        out = asyncio.run(
            NyaaAdapter("https://nyaa.si", http()).search(
                Query(media_type=MediaType.TV, text="anime")
            )
        )
    assert len(out) == 1
    assert out[0].seeds == 42
    assert out[0].size_bytes > 0
    assert out[0].infohash == "cafe1234"


def test_nyaa_bad_xml():
    with respx.mock:
        respx.get("https://nyaa.si/").mock(return_value=httpx.Response(200, text="<not rss"))
        with pytest.raises(SchemaMismatchError):
            asyncio.run(
                NyaaAdapter("https://nyaa.si", http()).search(
                    Query(media_type=MediaType.TV, text="x")
                )
            )
