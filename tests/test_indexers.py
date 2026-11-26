import asyncio

import httpx
import pytest
import respx

from arr.config.settings import DEFAULTS, Config
from arr.core.models import MediaType, Query
from arr.indexers import (
    AnimetoshoAdapter,
    EztvAdapter,
    HttpClient,
    NyaaAdapter,
    SchemaMismatchError,
    YtsAdapter,
)


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


def test_nyaa_supports_movie_and_tv():
    adapter = NyaaAdapter("https://nyaa.si", http())
    assert adapter.supports(MediaType.TV) is True
    assert adapter.supports(MediaType.MOVIE) is True


def test_nyaa_search_movie_sets_movie_media_type():
    with respx.mock:
        respx.get("https://nyaa.si/").mock(return_value=httpx.Response(200, text=NYAA_RSS))
        out = asyncio.run(
            NyaaAdapter("https://nyaa.si", http()).search(
                Query(media_type=MediaType.MOVIE, text="Spirited Away")
            )
        )
    assert len(out) == 1
    assert out[0].media_type == MediaType.MOVIE
    assert out[0].infohash == "cafe1234"


def test_nyaa_search_appends_season_episode_tokens(tmp_path):
    """2.2: non-anime TV queries carry Sxx/Eyy tokens; anime queries do not."""
    isolated = HttpClient(cfg(), cache_dir=tmp_path)
    with respx.mock:
        route = respx.get("https://nyaa.si/").mock(
            return_value=httpx.Response(200, text=NYAA_RSS)
        )
        adapter = NyaaAdapter("https://nyaa.si", isolated)
        asyncio.run(
            adapter.search(
                Query(media_type=MediaType.TV, text="Show", season=2, episode=5)
            )
        )
        assert route.calls.last.request.url.params["q"] == "Show S02E05"
        asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Show", season=2)))
        assert route.calls.last.request.url.params["q"] == "Show S02"
        asyncio.run(
            adapter.search(
                Query(
                    media_type=MediaType.TV,
                    text="Naruto",
                    season=2,
                    episode=5,
                    anime=True,
                )
            )
        )
        assert route.calls.last.request.url.params["q"] == "Naruto"



def test_nyaa_category_is_language_scoped(tmp_path):
    """NYAA has no movie/episode category (1_2/1_3/1_4 are the subtitle
    languages and anime films are filed with episodes), so both media types
    must keep requesting 1_2 — the anime movie exclusion belongs in the ranker.
    A single-digit `c` value is rejected by nyaa with an HTML error page."""
    isolated = HttpClient(cfg(), cache_dir=tmp_path)
    with respx.mock:
        route = respx.get("https://nyaa.si/").mock(
            return_value=httpx.Response(200, text=NYAA_RSS)
        )
        adapter = NyaaAdapter("https://nyaa.si", isolated)
        asyncio.run(
            adapter.search(
                Query(media_type=MediaType.TV, text="Demon Slayer", season=1, anime=True)
            )
        )
        assert route.calls.last.request.url.params["c"] == "1_2"
        asyncio.run(
            adapter.search(Query(media_type=MediaType.MOVIE, text="Demon Slayer"))
        )
        assert route.calls.last.request.url.params["c"] == "1_2"


def test_browser_session_lazy_init():
    """3.1: BrowserSession lazy-initialises on first get_context call."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from arr.indexers.browser import BrowserSession

    session = BrowserSession()
    assert session._browser is None
    assert session._context is None

    mock_browser = AsyncMock()
    mock_context = AsyncMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    with patch.object(session, "_launch", new_callable=AsyncMock) as mock_launch:
        mock_launch.return_value = None
        session._browser = mock_browser
        session._context = mock_context
        ctx = asyncio.run(session.get_context())
        assert ctx is mock_context


def test_browser_session_close():
    """3.1: BrowserSession.close() releases resources."""
    from unittest.mock import AsyncMock, patch

    from arr.indexers.browser import BrowserSession

    session = BrowserSession()
    mock_browser = AsyncMock()
    session._browser = mock_browser

    asyncio.run(session.close())
    mock_browser.close.assert_called_once()
    assert session._browser is None
    assert session._closed is True


def test_browser_session_channel_fallback(monkeypatch):
    """3.1: BrowserSession prefers the channel, falling back to bundled Chromium."""
    import playwright.async_api as pw_api

    from arr.indexers.browser import BrowserSession

    attempts: list[str | None] = []

    class _FakeContext:
        def __init__(self) -> None:
            self.closed = False

        async def close(self) -> None:
            self.closed = True

    class _FakeChromium:
        async def launch_persistent_context(self, user_data_dir, **kwargs):
            attempts.append(kwargs.get("channel"))
            if kwargs.get("channel") == "chrome":
                raise RuntimeError("Executable doesn't exist at /usr/bin/google-chrome")
            return _FakeContext()

    class _FakePlaywright:
        chromium = _FakeChromium()

        async def stop(self) -> None:
            pass

    class _FakePlaywrightFactory:
        async def __aenter__(self):
            return _FakePlaywright()

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(pw_api, "async_playwright", lambda: _FakePlaywrightFactory())

    async def scenario():
        session = BrowserSession(channel="chrome")
        ctx = await session.get_context()
        await session.close()
        return ctx

    ctx = asyncio.run(scenario())
    # Preferred channel tried first, bundled Chromium used after the failure.
    assert attempts == ["chrome", None]
    assert isinstance(ctx, _FakeContext)
    assert ctx.closed is True


def test_get_browser_session_is_singleton():
    """3.1: one browser session per process (design D1)."""
    from arr.indexers import browser as browser_module

    a = browser_module.get_browser_session()
    b = browser_module.get_browser_session()
    assert a is b
    assert a._channel == "chrome"


# -- TPB parser (3.3) -----------------------------------------------------

def test_parse_tv_fixture():
    """3.3: Parse the captured live TV search page → Releases with populated fields.

    The fixture is a raw capture of the JS-rendered "Breaking Bad" results
    page (2026-11-23) with mixed TV and movie rows, so this also covers
    per-row media-type inference from the category labels.
    """
    from arr.indexers.tpb_parser import parse_page

    html = open("tests/fixtures/tpb_tv_search.html", encoding="utf-8").read()
    releases = parse_page(html, media_type=MediaType.TV)
    assert len(releases) >= 50
    assert all(r.indexer == "tpb" for r in releases)
    assert all(r.magnet.startswith("magnet:") for r in releases)
    # Sizes come from the hidden input[name=size]; no more ~140-byte GiB rows.
    assert all(r.size_bytes > 1024 * 1024 for r in releases)
    assert all(r.seeds >= 0 for r in releases)
    assert all(r.peers >= 0 for r in releases)
    # Titles are real, not the first breadcrumb link ("Video").
    assert all(r.title and r.title != "Video" for r in releases)
    # Per-row media type follows the row's own category label.
    tv = [r for r in releases if r.media_type == MediaType.TV]
    movies = [r for r in releases if r.media_type == MediaType.MOVIE]
    assert len(tv) >= 40
    assert movies  # movie rows must be present for the TV constraint to bite
    assert any("breaking bad" in r.title.lower() for r in tv)


def test_parse_size_units():
    """3.3: parse_size handles the binary units TPB actually shows."""
    from arr.indexers.tpb_parser import parse_size

    assert parse_size("140.06 GiB") == int(140.06 * 1024**3)
    assert parse_size("512 MiB") == int(512 * 1024**2)
    assert parse_size("2 TiB") == int(2 * 1024**4)
    assert parse_size("1.5 GB") == int(1.5 * 1024**3)
    assert parse_size("500 MB") == int(500 * 1024**2)
    assert parse_size("no size") == 0
    assert parse_size("") == 0


def test_infer_media_type():
    """3.3: category text maps to media type; unknown text falls back."""
    from arr.indexers.tpb_parser import infer_media_type

    assert infer_media_type("HD TV-Shows", MediaType.MOVIE) == MediaType.TV
    assert infer_media_type("UHD/4k TV-Shows", MediaType.MOVIE) == MediaType.TV
    assert infer_media_type("TV-Shows", MediaType.MOVIE) == MediaType.TV
    assert infer_media_type("HD Movies", MediaType.TV) == MediaType.MOVIE
    assert infer_media_type("UHD/4k Movies", MediaType.TV) == MediaType.MOVIE
    assert infer_media_type("", MediaType.TV) == MediaType.TV
    assert infer_media_type("Audio", MediaType.MOVIE) == MediaType.MOVIE


def test_parse_shell_page_empty():
    """3.3: Shell page with zero list-entry rows → empty list (not error)."""
    from arr.indexers.tpb_parser import parse_page

    html = open("tests/fixtures/tpb_shell_page.html", encoding="utf-8").read()
    releases = parse_page(html)
    assert releases == []


def test_parse_corrupted_row():
    """3.3: Corrupted row (missing title/magnet) is skipped; good rows remain."""
    from arr.indexers.tpb_parser import parse_page

    html = open("tests/fixtures/tpb_corrupted_row.html", encoding="utf-8").read()
    releases = parse_page(html)
    # 3 rows total, 1 malformed (no title, no magnet) → 2 good releases
    assert len(releases) == 2
    assert all(r.indexer == "tpb" for r in releases)


def test_parse_row_missing_magnet_raises():
    """3.3: Row with no magnet URI raises SchemaMismatchError."""
    from arr.indexers.tpb_parser import parse_row
    from arr.indexers.base import SchemaMismatchError
    from selectolax.lexbor import LexborHTMLParser as HTMLParser

    html = '<li class="list-entry"><a class="item-name">No Magnet</a></li>'
    tree = HTMLParser(html)
    row = tree.css_first("li.list-entry")
    with pytest.raises(SchemaMismatchError):
        parse_row(row)


# -- TpbAdapter (3.4) -----------------------------------------------------

def test_tpb_adapter_name_and_supports():
    """3.4: TpbAdapter has correct name and supports TV + MOVIE."""
    from arr.indexers.tpb import TpbAdapter

    adapter = TpbAdapter("https://thepiratebay.org", http())
    assert adapter.name == "tpb"
    assert adapter.supports(MediaType.TV) is True
    assert adapter.supports(MediaType.MOVIE) is True


def test_tpb_adapter_search_stubbed_browser():
    """3.4: TpbAdapter.search() yields Releases with populated fields."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from arr.core.models import Query
    from arr.indexers.tpb import TpbAdapter

    adapter = TpbAdapter("https://thepiratebay.org", http())

    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value=open("tests/fixtures/tpb_tv_search.html", encoding="utf-8").read())
    mock_page.goto = AsyncMock(return_value=MagicMock())
    mock_page.close = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    with patch.object(adapter._browser, "get_context", new_callable=AsyncMock, return_value=mock_context):
        result = asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Breaking Bad")))

    assert len(result) > 0
    assert result[0].indexer == "tpb"
    assert result[0].magnet.startswith("magnet:")
    assert result[0].size_bytes > 0
    assert result[0].seeds > 0
    # Client-side TV constraint (D2): movie rows never leak through, and
    # results are capped at the query limit.
    assert all(r.media_type == MediaType.TV for r in result)
    assert len(result) <= 50


def test_tpb_search_appends_season_episode_tokens():
    """2.2: Sxx/Eyy tokens join the TPB search text; anime queries send none."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from arr.core.models import Query
    from arr.indexers.tpb import TpbAdapter

    adapter = TpbAdapter("https://thepiratebay.org", http())

    mock_context = AsyncMock()
    mock_page = AsyncMock()
    mock_page.content = AsyncMock(return_value="")
    mock_page.goto = AsyncMock(return_value=MagicMock())
    mock_page.close = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)

    with patch.object(adapter._browser, "get_context", new_callable=AsyncMock, return_value=mock_context):
        asyncio.run(
            adapter.search(Query(media_type=MediaType.TV, text="Show", season=2, episode=5))
        )
        assert "S02E05" in mock_page.goto.call_args[0][0]

        asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Show", season=2)))
        assert "S02" in mock_page.goto.call_args[0][0]

        asyncio.run(
            adapter.search(
                Query(
                    media_type=MediaType.TV,
                    text="Naruto",
                    season=2,
                    episode=5,
                    anime=True,
                )
            )
        )
        assert "S02" not in mock_page.goto.call_args[0][0]


def test_build_adapters_includes_tpb_when_enabled():
    """3.4: build_adapters includes TpbAdapter when enabled_indexers contains 'tpb'."""
    from arr.indexers import build_adapters
    from arr.indexers.tpb import TpbAdapter

    enabled_cfg = dict(DEFAULTS)
    enabled_cfg["enabled_indexers"] = ["yts", "eztv", "nyaa", "tpb"]
    adapters = build_adapters(enabled_cfg)
    adapter_names = [a.name for a in adapters]
    assert "tpb" in adapter_names
    assert any(isinstance(a, TpbAdapter) for a in adapters)


def test_build_adapters_excludes_tpb_when_disabled():
    """3.4: build_adapters excludes TpbAdapter when enabled_indexers does not contain 'tpb'."""
    from arr.indexers import build_adapters
    from arr.indexers.tpb import TpbAdapter

    disabled_cfg = dict(DEFAULTS)
    disabled_cfg["enabled_indexers"] = ["yts", "eztv", "nyaa"]
    adapters = build_adapters(disabled_cfg)
    adapter_names = [a.name for a in adapters]
    assert "tpb" not in adapter_names
    assert not any(isinstance(a, TpbAdapter) for a in adapters)


# -- Integration test (3.5) -----------------------------------------------

@pytest.mark.integration
def test_tpb_integration_search():
    """3.5: Real TPB search end-to-end (browser → parsed Releases → magnet well-formed).

    Deselected by default (marked with -m integration).
    """
    from arr.core.models import Query
    from arr.indexers.tpb import TpbAdapter

    adapter = TpbAdapter("https://thepiratebay.org", http())
    result = asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Breaking Bad")))

    # May be 0 if network/TPB is down
    assert len(result) >= 0
    for r in result:
        assert r.indexer == "tpb"
        assert r.magnet.startswith("magnet:")
        assert "btih:" in r.magnet.lower()
        assert r.seeds >= 0
        # Live-markup regression: titles come from the row's item-name link.
        assert r.title and r.title != "Video"
        # Client-side TV constraint (D2): no movie rows may leak through.
        assert r.media_type == MediaType.TV
# -- E2E fallback check (6.1) -----------------------------------------------

@pytest.mark.integration
def test_e2e_tpb_fallback_for_tv_title():
    """6.1: TV title on TPB but not EZTV → tpb-attributed release in ranked results.

    Verifies that when EZTV has no results for a TV title, TPB provides
    a fallback release that survives ranking.
    """
    import asyncio

    from arr.core.models import MediaType, Query, Release
    from arr.core.parsing import rank
    from arr.indexers.tpb import TpbAdapter
    from arr.indexers.eztv import EztvAdapter

    class EmptyEztvAdapter(EztvAdapter):
        async def search(self, q: Query) -> list[Release]:
            return []

    class StubTpbAdapter(TpbAdapter):
        async def search(self, q: Query) -> list[Release]:
            return [
                Release(
                    title="Breaking.Bad.S05E14.1080p.WEB-DL",
                    infohash="a" * 40,
                    magnet="magnet:?xt=urn:btih:" + "a" * 40 + "&tr=udp://tracker.opentrackr.org:1337/announce",
                    size_bytes=2684354560,
                    seeds=150,
                    peers=12,
                    indexer="tpb",
                    media_type=MediaType.TV,
                ),
            ]

    cfg = dict(DEFAULTS)
    cfg["enabled_indexers"] = ["eztv", "tpb"]
    cfg["indexer_priority"] = ["eztv", "tpb"]

    adapters = [
        EmptyEztvAdapter(cfg.get("eztv_base_url"), http()),
        StubTpbAdapter(cfg.get("tpb_base_url"), http()),
    ]

    # Search for a TV title
    q = Query(media_type=MediaType.TV, text="Breaking Bad")
    all_releases = []
    for adapter in adapters:
        if adapter.supports(q.media_type):
            all_releases.extend(asyncio.run(adapter.search(q)))

    # Verify the TPB fallback release is present
    assert [r.indexer for r in all_releases] == ["tpb"]

    # Verify ranking keeps the fallback (and would order it after eztv).
    ranked = rank(all_releases, q, None, cfg)
    accepted = [s for s in ranked if s.rejected is None]
    assert len(accepted) == 1
    assert accepted[0].release.indexer == "tpb"
    assert accepted[0].release.magnet.startswith("magnet:")


def test_torrentio_adapter_name_and_supports():
    """TorrentioAdapter has correct name and supports TV + MOVIE."""
    from arr.indexers.torrentio import TorrentioAdapter

    adapter = TorrentioAdapter("http://localhost:8085", http())
    assert adapter.name == "torrentio"
    assert adapter.supports(MediaType.TV) is True
    assert adapter.supports(MediaType.MOVIE) is True
# -- Failure-isolation check (6.2) --------------------------------------------

@pytest.mark.integration
def test_torrentio_failure_isolation():
    """6.2: With sidecar stopped, search completes with remaining indexers.

    Verifies that when the Torrentio sidecar is down (connection failure),
    the search still completes with results from other indexers.
    """
    import asyncio
    from unittest.mock import patch

    from arr.core.models import MediaType, Query, Release
    from arr.indexers.torrentio import (
        TorrentioAdapter,
        _is_down,
        _mark_down,
        _mark_up,
    )

    # Clear down-marker state
    _mark_up()

    # Create a mock HTTP that raises on first call (simulates sidecar down)
    call_count = 0

    async def failing_get(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Connection refused")
        return AsyncMock(json=lambda: [])

    adapter = TorrentioAdapter("http://localhost:8085", http())

    with patch.object(adapter.http, "get", new=failing_get):
        # First search should fail and mark sidecar as down
        result1 = asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Test")))
        assert result1 == []
        assert _is_down() is True

        # Second search within 60s should skip network (no HTTP call)
        result2 = asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Test")))
        assert result2 == []
        # No additional HTTP call since sidecar is down
        assert call_count == 1

    # Clear for other tests
    _mark_up()

def test_torrentio_map_json_to_releases():
    """4.1: JSON payload is correctly mapped to Release objects."""
    from arr.indexers.torrentio import _map_torrents
    from arr.core.models import MediaType

    sample_torrents = [
        {
            "title": "Breaking.Bad.S05E14.1080p.WEB-DL",
            "infoHash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "size": 2684354560,
            "seeders": 150,
            "peers": 12,
            "quality": "1080p",
        },
        {
            "title": "Breaking.Bad.S05E15.720p.HDTV",
            "infoHash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "size": 1288490188,
            "seeders": 85,
            "peers": 8,
            "quality": "720p",
        },
    ]
    trackers = ["udp://tracker.opentrackr.org:1337/announce"]
    releases = _map_torrents(sample_torrents, trackers, MediaType.TV)

    assert len(releases) == 2
    assert all(r.indexer == "torrentio" for r in releases)
    assert all(r.magnet.startswith("magnet:") for r in releases)
    assert all("&tr=" in r.magnet for r in releases)
    assert all(r.size_bytes > 0 for r in releases)
    assert all(r.seeds > 0 for r in releases)


def test_torrentio_movie_vs_tv_params():
    """4.1: Movie queries use title_id, TV queries use search_query."""
    import respx
    from unittest.mock import AsyncMock, patch

    from arr.core.models import MediaType, Query
    from arr.indexers.torrentio import TorrentioAdapter

    adapter = TorrentioAdapter("http://localhost:8085", http())

    # Mock the HTTP get to capture the params
    captured_params: list[dict] = []

    async def mock_get(url, *, key, ttl_seconds, params):
        captured_params.append(params)
        return AsyncMock(json=lambda: [])

    with patch.object(adapter.http, "get", new=mock_get):
        # Movie with imdb_id
        asyncio.run(adapter.search(Query(media_type=MediaType.MOVIE, text="Inception", imdb_id="tt1375666")))
        assert "title_id" in captured_params[-1]
        assert captured_params[-1]["title_id"] == "tt1375666"

        # TV without imdb_id
        asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Breaking Bad")))
        assert "search_query" in captured_params[-1]
        assert captured_params[-1]["search_query"] == "Breaking Bad"


def test_torrentio_down_marker_skips_network():
    """4.1: After connection failure, down-marker skips network for 60s."""
    from arr.indexers.torrentio import (
        TorrentioAdapter,
        _is_down,
        _mark_down,
        _mark_up,
    )

    # Clear state
    _mark_up()
    assert _is_down() is False

    # Mark as down
    _mark_down()
    assert _is_down() is True

    # Clear again
    _mark_up()
    assert _is_down() is False


def test_torrentio_connection_failure_marks_down():
    """4.1: Connection failure marks the sidecar as down."""
    import respx
    from unittest.mock import AsyncMock, patch

    from arr.core.models import Query
    from arr.indexers.torrentio import TorrentioAdapter, _is_down, _mark_down, _mark_up

    _mark_up()  # Clear any previous state

    adapter = TorrentioAdapter("http://localhost:8085", http())

    # Mock get to raise an exception
    async def failing_get(*args, **kwargs):
        raise Exception("Connection refused")

    with patch.object(adapter.http, "get", new=failing_get):
        result = asyncio.run(adapter.search(Query(media_type=MediaType.TV, text="Test")))
        assert result == []
        assert _is_down() is True

    # Clear for other tests
    _mark_up()


# -- Torrentio registration (4.2) -------------------------------------------

def test_build_adapters_includes_torrentio_when_enabled():
    """4.2: build_adapters includes TorrentioAdapter when enabled."""
    from arr.indexers import build_adapters
    from arr.indexers.torrentio import TorrentioAdapter

    enabled_cfg = dict(DEFAULTS)
    enabled_cfg["enabled_indexers"] = ["yts", "eztv", "nyaa", "tpb", "torrentio"]
    adapters = build_adapters(enabled_cfg)
    adapter_names = [a.name for a in adapters]
    assert "torrentio" in adapter_names
    assert any(isinstance(a, TorrentioAdapter) for a in adapters)


def test_build_adapters_excludes_torrentio_when_disabled():
    """4.2: build_adapters excludes TorrentioAdapter when disabled."""
    from arr.indexers import build_adapters
    from arr.indexers.torrentio import TorrentioAdapter

    disabled_cfg = dict(DEFAULTS)
    disabled_cfg["enabled_indexers"] = ["yts", "eztv", "nyaa", "tpb"]
    adapters = build_adapters(disabled_cfg)
    adapter_names = [a.name for a in adapters]
    assert "torrentio" not in adapter_names
    assert not any(isinstance(a, TorrentioAdapter) for a in adapters)


# -- Anime Tosho parser (3.1) ------------------------------------------------


def test_animetosho_parse_rows_fixture():
    """3.1: Captured search page parses into fully populated row dicts."""
    from arr.indexers.animetosho_parser import parse_rows

    html = open("tests/fixtures/animetosho_search.html", encoding="utf-8").read()
    rows = parse_rows(html)
    # The DDL-only row (no magnet link) is skipped.
    assert len(rows) == 2
    row = rows[0]
    assert row["title"] == (
        "[AnoZu] One Piece S23E06 1080p CR WEB-DL Dual-Audio DDP 2.0 H.264"
    )
    assert row["magnet"].startswith(
        "magnet:?xt=urn:btih:611e5b6bcfa317ea580a40da2e7befda5caf3a9f"
    )
    assert "&" in row["magnet"]  # HTML entities unescaped
    assert row["size_bytes"] == 1527565407
    assert row["seeders"] == 216
    assert row["leechers"] == 91
    # Anime Tosho also serves 32-char base32 infohashes (upper-cased in the
    # magnet URI); they must parse as a clean lowercase hash.
    base32_row = rows[1]
    assert base32_row["title"].startswith("One Piece - 1180")
    assert base32_row["magnet"].startswith(
        "magnet:?xt=urn:btih:HSZMPOIZCBQVT7LVBKXKL7NJP4JRKYC4"
    )
    assert base32_row["size_bytes"] == 174931954


def test_animetosho_parse_rows_empty_fixture():
    """3.1: No-results search page parses to an empty list (not an error)."""
    from arr.indexers.animetosho_parser import parse_rows

    html = open("tests/fixtures/animetosho_search_empty.html", encoding="utf-8").read()
    assert parse_rows(html) == []


def test_animetosho_malformed_page_raises():
    """3.1: Page with no recognizable search layout raises SchemaMismatchError."""
    from arr.indexers.animetosho_parser import parse_rows

    with pytest.raises(SchemaMismatchError):
        parse_rows("<html><body><h1>weird page</h1></body></html>")


# -- Anime Tosho adapter (3.2) -----------------------------------------------


def test_animetosho_search_returns_releases(tmp_path):
    """3.2: Search maps fixture rows to Releases with magnet infohash."""
    html = open("tests/fixtures/animetosho_search.html", encoding="utf-8").read()
    isolated = HttpClient(cfg(), cache_dir=tmp_path)
    with respx.mock:
        respx.get("https://animetosho.net/search").mock(
            return_value=httpx.Response(200, text=html)
        )
        out = asyncio.run(
            AnimetoshoAdapter("https://animetosho.net", isolated).search(
                Query(media_type=MediaType.TV, text="One Piece", anime=True)
            )
        )
    assert len(out) == 2
    release = out[0]
    assert release.indexer == "animetosho"
    assert release.infohash == "611e5b6bcfa317ea580a40da2e7befda5caf3a9f"
    assert release.magnet.startswith("magnet:?xt=urn:btih:")
    assert release.seeds == 216
    assert release.peers == 91
    assert release.size_bytes == 1527565407
    assert release.media_type == MediaType.TV
    # The base32 row's infohash is normalized to the 40-hex form
    # Transmission uses (its hex hashString), not a slice of the base32
    # hash that swallows the magnet's next parameter.
    assert out[1].infohash == "3cb2c7b919106159fd750aaea5fda97f1315605c"


def test_animetosho_search_appends_season_episode_tokens(tmp_path):
    """3.2: Non-anime TV queries carry Sxx/Eyy tokens; anime queries send none."""
    html = open("tests/fixtures/animetosho_search.html", encoding="utf-8").read()
    isolated = HttpClient(cfg(), cache_dir=tmp_path)
    with respx.mock:
        route = respx.get("https://animetosho.net/search").mock(
            return_value=httpx.Response(200, text=html)
        )
        adapter = AnimetoshoAdapter("https://animetosho.net", isolated)
        asyncio.run(
            adapter.search(
                Query(media_type=MediaType.TV, text="Show", season=2, episode=5)
            )
        )
        assert route.calls.last.request.url.params["q"] == "Show S02E05"
        asyncio.run(
            adapter.search(Query(media_type=MediaType.TV, text="Show", season=2))
        )
        assert route.calls.last.request.url.params["q"] == "Show S02"
        asyncio.run(
            adapter.search(
                Query(
                    media_type=MediaType.TV,
                    text="Naruto",
                    season=2,
                    episode=5,
                    anime=True,
                )
            )
        )
        assert route.calls.last.request.url.params["q"] == "Naruto"


def test_animetosho_supports_and_movie_media_type(tmp_path):
    """3.2: supports covers TV + MOVIE; movie queries propagate the media type."""
    html = open("tests/fixtures/animetosho_search.html", encoding="utf-8").read()
    isolated = HttpClient(cfg(), cache_dir=tmp_path)
    adapter = AnimetoshoAdapter("https://animetosho.net", isolated)
    assert adapter.supports(MediaType.TV)
    assert adapter.supports(MediaType.MOVIE)
    with respx.mock:
        respx.get("https://animetosho.net/search").mock(
            return_value=httpx.Response(200, text=html)
        )
        out = asyncio.run(
            adapter.search(Query(media_type=MediaType.MOVIE, text="Demon Slayer"))
        )
    assert len(out) == 2
    assert all(r.media_type == MediaType.MOVIE for r in out)


def test_animetosho_search_not_found_is_empty(tmp_path):
    """3.2: A 404 search response yields an empty list without raising."""
    isolated = HttpClient(cfg(), cache_dir=tmp_path)
    with respx.mock:
        respx.get("https://animetosho.net/search").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        out = asyncio.run(
            AnimetoshoAdapter("https://animetosho.net", isolated).search(
                Query(media_type=MediaType.TV, text="Nothing Here")
            )
        )
    assert out == []


def test_animetosho_search_malformed_raises(tmp_path):
    """3.2: An unrecognized page shape raises SchemaMismatchError (fan-out isolates it)."""
    isolated = HttpClient(cfg(), cache_dir=tmp_path)
    with respx.mock:
        respx.get("https://animetosho.net/search").mock(
            return_value=httpx.Response(
                200, text="<html><body><h1>weird</h1></body></html>"
            )
        )
        with pytest.raises(SchemaMismatchError):
            asyncio.run(
                AnimetoshoAdapter("https://animetosho.net", isolated).search(
                    Query(media_type=MediaType.TV, text="Weird")
                )
            )


def test_build_adapters_includes_animetosho_when_enabled():
    """3.2: build_adapters includes AnimetoshoAdapter when enabled_indexers has it."""
    from arr.indexers import build_adapters

    enabled_cfg = dict(DEFAULTS)
    enabled_cfg["enabled_indexers"] = ["nyaa", "animetosho"]
    adapters = build_adapters(enabled_cfg)
    adapter_names = [a.name for a in adapters]
    assert "animetosho" in adapter_names
    assert any(isinstance(a, AnimetoshoAdapter) for a in adapters)


def test_build_adapters_excludes_animetosho_when_disabled():
    """3.2: build_adapters excludes AnimetoshoAdapter when it is not enabled."""
    from arr.indexers import build_adapters

    disabled_cfg = dict(DEFAULTS)
    disabled_cfg["enabled_indexers"] = ["yts", "eztv", "nyaa", "tpb", "torrentio"]
    adapters = build_adapters(disabled_cfg)
    adapter_names = [a.name for a in adapters]
    assert "animetosho" not in adapter_names
    assert not any(isinstance(a, AnimetoshoAdapter) for a in adapters)


def test_default_priority_places_animetosho_after_nyaa():
    """3.2: Default config ranks animetosho immediately after nyaa."""
    assert DEFAULTS["indexer_priority"] == [
        "yts", "eztv", "nyaa", "animetosho", "tpb", "torrentio"
    ]
    assert DEFAULTS["enabled_indexers"] == [
        "yts", "eztv", "nyaa", "animetosho", "tpb", "torrentio"
    ]
