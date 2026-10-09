"""Tests for scraping-based metadata and subtitle clients using fake sessions (no network)."""

from arr.config.settings import DEFAULTS, Config
from arr.metadata.imdb import ImdbClient, ImdbError
from arr.subtitles.base import SubtitleError
from arr.subtitles.subscene import SubsceneClient
from arr.subtitles.yify import YifySubtitlesClient


class FakeResponse:
    def __init__(self, status_code=200, text="", content=b""):
        self.status_code = status_code
        self.text = text
        self.content = content or text.encode("utf-8")


class FakeSession:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, timeout=None, **kw):
        self.calls.append(url)
        for key, resp in self.routes.items():
            if key in url:
                return resp
        return FakeResponse(404, "not found")


def cfg():
    return Config(values=dict(DEFAULTS))


# --------------------------- IMDb ---------------------------

IMDB_SEARCH_HTML = """
<html><body>
  <li class="find-title-result">
    <a href="/title/tt1375666/?ref_=fn_al_tt_1">Inception</a>
    <span>2010</span>
  </li>
</body></html>
"""

IMDB_TITLE_HTML = """
<html><head>
  <meta property="og:title" content="Inception (2010) - IMDb" />
</head><body><h1>Inception</h1></body></html>
"""


def test_imdb_search_movie(tmp_path):
    session = FakeSession({"/find/": FakeResponse(200, IMDB_SEARCH_HTML)})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    m = c.search_movie("inception")
    assert m is not None
    assert m["imdb_id"] == "tt1375666"
    assert m["title"] == "Inception"
    assert m["year"] == 2010


def test_imdb_search_movies_multiple(tmp_path):
    multi_html = """
    <html><body>
      <li><a href="/title/tt1111111/">Movie One</a><span>2021</span></li>
      <li><a href="/title/tt2222222/">Movie Two</a><span>2022</span></li>
    </body></html>
    """
    session = FakeSession({"/find/": FakeResponse(200, multi_html)})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    movies = c.search_movies("test")
    assert len(movies) == 2
    assert movies[0]["imdb_id"] == "tt1111111"
    assert movies[0]["title"] == "Movie One"
    assert movies[0]["year"] == 2021
    assert movies[1]["imdb_id"] == "tt2222222"
    assert movies[1]["title"] == "Movie Two"
    assert movies[1]["year"] == 2022



def test_imdb_movie_details(tmp_path):
    session = FakeSession({"/title/tt1375666/": FakeResponse(200, IMDB_TITLE_HTML)})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    d = c.movie_details("tt1375666")
    assert d["title"] == "Inception"
    assert d["year"] == 2010


def test_imdb_search_no_results(tmp_path):
    session = FakeSession({"/find/": FakeResponse(200, "<html><body></body></html>")})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    assert c.search_movie("zzz") is None


def test_imdb_returns_none_when_all_sources_fail(tmp_path):
    session = FakeSession(
        {
            "/find/": FakeResponse(503, "blocked"),
            "/suggestion/": FakeResponse(503, "blocked"),
        }
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    assert c.search_movie("x") is None


def test_imdb_movie_details_raises_on_http_error(tmp_path):
    session = FakeSession({"/title/": FakeResponse(503, "blocked")})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    try:
        c.movie_details("tt1")
    except ImdbError:
        return
    raise AssertionError("expected ImdbError")


def test_imdb_cache_hit_avoids_second_fetch(tmp_path):
    session = FakeSession({"/find/": FakeResponse(200, IMDB_SEARCH_HTML)})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    c.search_movie("inception")
    c.search_movie("inception")
    assert len(session.calls) == 1


IMDB_SUGGESTION_JSON = """
{"d": [
  {"id": "tt1375666", "l": "Inception", "y": 2010, "q": "feature"},
  {"id": "tt1790736", "l": "Inception: The Cobol Job", "y": 2010, "q": "video"}
]}
"""


def test_imdb_falls_back_to_suggestion_when_html_blocked(tmp_path):
    session = FakeSession(
        {
            "/find/": FakeResponse(202, "blocked"),
            "/suggestion/": FakeResponse(200, IMDB_SUGGESTION_JSON),
        }
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    m = c.search_movie("inception")
    assert m is not None
    assert m["imdb_id"] == "tt1375666"
    assert m["title"] == "Inception"
    assert m["year"] == 2010


def test_imdb_suggestion_skips_non_title_entries(tmp_path):
    payload = '{"d": [{"id": "nm0000138", "l": "Leonardo DiCaprio"}]}'
    session = FakeSession(
        {
            "/find/": FakeResponse(200, "<html></html>"),
            "/suggestion/": FakeResponse(200, payload),
        }
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)
    assert c.search_movie("leo") is None


# --------------------------- Subscene ---------------------------

SUBSCENE_SEARCH_HTML = """
<html><body>
  <a href="/subtitles/inception-2010">Inception (2010)</a>
</body></html>
"""

SUBSCENE_TITLE_HTML = """
<html><body>
  <ul>
    <li>
      <a href="/subtitle/inception-english-12345">
        Inception.2010.1080p.BluRay English
      </a>
    </li>
    <li>
      <a href="/subtitle/inception-french-99999">
        Inception.2010.1080p.BluRay French
      </a>
    </li>
  </ul>
</body></html>
"""


def test_subscene_search_maps_english_candidates():
    session = FakeSession(
        {
            "/subtitles/searchbytitle": FakeResponse(200, SUBSCENE_SEARCH_HTML),
            "/subtitles/inception-2010": FakeResponse(200, SUBSCENE_TITLE_HTML),
        }
    )
    c = SubsceneClient("https://subscene.com", session=session)
    out = c.search(title="Inception", languages=["en"])
    assert len(out) == 1
    assert out[0].language == "en"
    assert "12345" in out[0].download_link


def test_subscene_no_title_match_returns_empty():
    session = FakeSession(
        {"/subtitles/searchbytitle": FakeResponse(200, "<html><body></body></html>")}
    )
    c = SubsceneClient("https://subscene.com", session=session)
    assert c.search(title="Nothing") == []


def test_subscene_http_error_raises():
    session = FakeSession({"/subtitles/searchbytitle": FakeResponse(500, "err")})
    c = SubsceneClient("https://subscene.com", session=session)
    try:
        c.search(title="X")
    except SubtitleError:
        return
    raise AssertionError("expected SubtitleError")


# --------------------------- YIFY ---------------------------

YIFY_MOVIE_HTML = """
<html><body>
  <table>
    <tr class="subtitle-row">
      <td><a href="/subtitle/inception-english-777">Inception English</a></td>
    </tr>
  </table>
</body></html>
"""

YIFY_SEARCH_HTML = """
<html><body>
  <a href="/movie-imdb/tt1375666">Inception</a>
</body></html>
"""


def test_yify_search_by_imdb():
    session = FakeSession(
        {"/movie-imdb/tt1375666": FakeResponse(200, YIFY_MOVIE_HTML)}
    )
    c = YifySubtitlesClient("https://yifysubtitles.ch", session=session)
    out = c.search(imdb_id="tt1375666", languages=["en"])
    assert len(out) == 1
    assert out[0].language == "en"
    assert "777" in out[0].download_link


def test_yify_search_by_title_finds_movie_page():
    session = FakeSession(
        {
            "/search": FakeResponse(200, YIFY_SEARCH_HTML),
            "/movie-imdb/tt1375666": FakeResponse(200, YIFY_MOVIE_HTML),
        }
    )
    c = YifySubtitlesClient("https://yifysubtitles.ch", session=session)
    out = c.search(title="Inception", languages=["en"])
    assert len(out) == 1


def test_yify_no_identifier_returns_empty():
    c = YifySubtitlesClient("https://yifysubtitles.ch", session=FakeSession({}))
    assert c.search() == []
