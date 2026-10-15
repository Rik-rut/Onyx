"""Tests for scraping-based metadata and subtitle clients using fake sessions (no network)."""

import json

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


# ------------------- IMDb discovery (R4.1/R4.2) -------------------


def _chart_html(items: list[dict], *, key: str = "chartTitles") -> str:
    payload = {
        "props": {
            "pageProps": {
                "pageData": {
                    key: {"edges": [{"node": item} for item in items]},
                }
            }
        }
    }
    return (
        "<html><body><script id=\"__NEXT_DATA__\" type=\"application/json\">"
        + json.dumps(payload)
        + "</script></body></html>"
    )


MOVIEMETER_ITEMS = [
    {
        "id": "tt1375666",
        "titleText": {"text": "Inception"},
        "releaseYear": {"year": 2010},
        "primaryImage": {"url": "https://img.example/inception.jpg"},
        "ratingsSummary": {"aggregateRating": 8.8},
    },
    {
        "id": "tt0111161",
        "titleText": {"text": "The Shawshank Redemption"},
        "releaseYear": {"year": 1994},
        "primaryImage": {"url": "https://img.example/shawshank.jpg"},
        "ratingsSummary": {"aggregateRating": 9.3},
    },
]


def test_imdb_trending_movies_from_chart(tmp_path):
    session = FakeSession(
        {"/chart/moviemeter/": FakeResponse(200, _chart_html(MOVIEMETER_ITEMS))}
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    items = c.trending_movies(limit=10)

    assert [i["imdb_id"] for i in items] == ["tt1375666", "tt0111161"]
    assert items[0]["title"] == "Inception"
    assert items[0]["year"] == 2010
    assert items[0]["poster"] == "https://img.example/inception.jpg"
    assert items[0]["rating"] == 8.8
    assert items[0]["media_type"] == "movie"


def test_imdb_trending_tv_and_top_rated(tmp_path):
    session = FakeSession(
        {
            "/chart/tvmeter/": FakeResponse(200, _chart_html(MOVIEMETER_ITEMS)),
            "/chart/top/": FakeResponse(
                200,
                _chart_html(
                    [dict(MOVIEMETER_ITEMS[1], currentRank=1), dict(MOVIEMETER_ITEMS[0])]
                ),
            ),
        }
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    tv = c.trending_tv(limit=5)
    assert tv[0]["imdb_id"] == "tt1375666"
    assert tv[0]["media_type"] == "tv"

    top = c.top_rated_movies(limit=5)
    assert [i["imdb_id"] for i in top] == ["tt0111161", "tt1375666"]
    assert top[0]["rank"] == 1


def test_imdb_trending_movies_falls_back_offline(tmp_path):
    """Bot-blocked charts still return a usable curated Discover rail."""
    session = FakeSession({"/chart/moviemeter/": FakeResponse(503, "blocked")})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    items = c.trending_movies(limit=3)

    assert len(items) == 3
    assert all(i["imdb_id"].startswith("tt") for i in items)
    assert all(i["title"] for i in items)


def test_imdb_movies_by_genre(tmp_path):
    session = FakeSession(
        {
            "/search/title/": FakeResponse(200, _chart_html(MOVIEMETER_ITEMS, key="titleResults"))
        }
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    items = c.movies_by_genre("action", limit=5)

    assert [i["imdb_id"] for i in items] == ["tt1375666", "tt0111161"]
    assert "genres=action" in "".join(session.calls)


MOVIE_DETAILS_PAYLOAD = {
    "props": {
        "pageProps": {
            "aboveTheFoldData": {
                "id": "tt1375666",
                "titleText": {"text": "Inception"},
                "releaseYear": {"year": 2010},
                "runtime": {"seconds": 8880},
                "ratingsSummary": {"aggregateRating": 8.8, "voteCount": 2500000},
                "genres": {"genres": [{"text": "Action"}, {"text": "Sci-Fi"}]},
                "plot": {"plotText": {"plainText": "A thief who steals corporate secrets."}},
                "primaryImage": {"url": "https://img.example/inception.jpg"},
                "principalCredits": [
                    {
                        "credits": [
                            {"name": {"nameText": {"text": "Christopher Nolan"}}},
                            {"name": {"nameText": {"text": "Leonardo DiCaprio"}}},
                        ]
                    }
                ],
            },
            "mainColumnData": {
                "moreLikeThisTitles": {
                    "edges": [
                        {
                            "node": {
                                "id": "tt0209144",
                                "titleText": {"text": "Memento"},
                                "releaseYear": {"year": 2000},
                                "primaryImage": {"url": "https://img.example/memento.jpg"},
                                "ratingsSummary": {"aggregateRating": 8.4},
                            }
                        }
                    ]
                }
            },
        }
    }
}


def test_imdb_rich_movie_details_with_similar(tmp_path):
    html = (
        "<html><body><script id=\"__NEXT_DATA__\" type=\"application/json\">"
        + json.dumps(MOVIE_DETAILS_PAYLOAD)
        + "</script></body></html>"
    )
    session = FakeSession({"/title/tt1375666/": FakeResponse(200, html)})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    d = c.movie_details("tt1375666")

    assert d["title"] == "Inception"
    assert d["year"] == 2010
    assert d["rating"] == 8.8
    assert d["genres"] == ["Action", "Sci-Fi"]
    assert d["runtime"] == 148
    assert "thief" in d["overview"]
    assert d["poster"] == "https://img.example/inception.jpg"
    assert d["stars"] == ["Christopher Nolan", "Leonardo DiCaprio"]
    assert [s["imdb_id"] for s in d["similar"]] == ["tt0209144"]
    assert d["similar"][0]["title"] == "Memento"


def test_imdb_curated_fallback_enriched_with_suggestion_posters(tmp_path):
    """Blocked charts still get posters/stars from the suggestion endpoint."""
    suggestion_json = json.dumps(
        {
            "d": [
                {
                    "id": "tt1375666",
                    "l": "Inception",
                    "y": 2010,
                    "rank": 219,
                    "s": "Leonardo DiCaprio, Joseph Gordon-Levitt",
                    "i": {"imageUrl": "https://img.example/inception.jpg"},
                }
            ]
        }
    )
    session = FakeSession(
        {
            "/chart/moviemeter/": FakeResponse(503, "blocked"),
            "/suggestion/": FakeResponse(200, suggestion_json),
        }
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    items = c.trending_movies(limit=3)

    first = items[0]
    assert first["poster"] == "https://img.example/inception.jpg"
    assert first["stars"] == "Leonardo DiCaprio, Joseph Gordon-Levitt"
    assert first["rating"]  # curated ratings keep the Discover rails useful


def test_imdb_movie_details_degrades_to_suggestion_when_blocked(tmp_path):
    """A bot-blocked title page must still return usable details, not an error."""
    suggestion_json = json.dumps(
        {
            "d": [
                {
                    "id": "tt1375666",
                    "l": "Inception",
                    "y": 2010,
                    "rank": 219,
                    "s": "Leonardo DiCaprio, Joseph Gordon-Levitt",
                    "i": {"imageUrl": "https://img.example/inception.jpg"},
                }
            ]
        }
    )
    session = FakeSession(
        {
            "/title/tt1375666/": FakeResponse(202, "<html><body>challenge</body></html>"),
            "/suggestion/": FakeResponse(200, suggestion_json),
        }
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    d = c.movie_details("tt1375666")

    assert d["title"] == "Inception"
    assert d["year"] == 2010
    assert d["poster"] == "https://img.example/inception.jpg"
    assert d["stars"] == ["Leonardo DiCaprio", "Joseph Gordon-Levitt"]
    assert d["degraded"] is True
    # genre-based recommendations keep the "More Like This" rail populated
    assert all(s["imdb_id"] != "tt1375666" for s in d["similar"])


def test_imdb_genre_fallback_has_no_duplicates(tmp_path):
    session = FakeSession(
        {"/search/title/": FakeResponse(503, "blocked"), "/suggestion/": FakeResponse(404, "")}
    )
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    items = c.movies_by_genre("action", limit=8)

    ids = [i["imdb_id"] for i in items]
    assert len(ids) == len(set(ids))


def test_imdb_movie_details_jsonld_fallback_and_genre_similar(tmp_path):
    """Without __NEXT_DATA__ the JSON-LD block still yields rich details."""
    html = """
    <html><head>
      <script type="application/ld+json">
      {"@type":"Movie","name":"Inception","aggregateRating":{"ratingValue":8.8},
       "genre":["Action"],"duration":"PT2H28M","description":"A thief.",
       "image":"https://img.example/i.jpg","datePublished":"2010-07-16"}
      </script>
      <meta property="og:title" content="Inception (2010) - IMDb" />
    </head><body><h1>Inception</h1></body></html>
    """
    session = FakeSession({"/title/tt1375666/": FakeResponse(200, html)})
    c = ImdbClient(cfg(), cache_dir=tmp_path, session=session)

    d = c.movie_details("tt1375666")

    assert d["title"] == "Inception"
    assert d["year"] == 2010
    assert d["rating"] == 8.8
    assert d["runtime"] == 148
    assert d["genres"] == ["Action"]
    # no More Like This block -> genre-matched recommendations are used
    assert d["similar"]
    assert all(s["imdb_id"] != "tt1375666" for s in d["similar"])


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
