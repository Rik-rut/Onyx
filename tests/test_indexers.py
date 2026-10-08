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
    assert out[0].magnet.startswith("magnet:")


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
