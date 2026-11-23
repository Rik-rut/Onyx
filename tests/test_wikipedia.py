"""Keyless Wikipedia/Wikidata movie enrichment, stubbed with respx (no network)."""

from __future__ import annotations

import httpx
import pytest
import respx

from arr.config.settings import DEFAULTS, Config
from arr.metadata import wikipedia

API = "https://en.wikipedia.org/w/api.php"
ENTITY = "https://www.wikidata.org/wiki/Special:EntityData"
WD_API = "https://www.wikidata.org/w/api.php"

INCEPTION_INTRO = (
    "Inception (also known as Mysterious Land in some markets) is a 2010 "
    "science fiction action adventure heist film produced by Syncopy Inc. "
    "The film stars actors including Heath Ledger."
)
OPPENHEIMER_PERSON = (
    "J. Robert Oppenheimer (April 24, 1904 - February 16, 1967) was an "
    "American theoretical physicist and professor at Harvard."
)
OPPENHEIMER_FILM = (
    "Oppenheimer is a 2025 biographical epic action war drama film based on "
    "the life of J. Robert Oppenheimer, directed by Christopher Nolan."
)
INCEPTION_WIKITEXT = (
    "{{Infobox Film\n"
    "| director = Christopher Nolan\n"
    "| runtime = 148 minutes<ref name=bb/>\n"
    "| country = United States\n"
    "}}"
)


def cfg() -> Config:
    return Config(values=dict(DEFAULTS))


def pages_payload(title: str, extract: str, qid: str | None = None) -> dict:
    page: dict = {"pageid": 1, "title": title, "extract": extract}
    if qid:
        page["pageprops"] = {"wikibase_item": qid}
    return {"query": {"pages": [page]}}


def search_payload(titles: list[str]) -> dict:
    return {"query": {"search": [{"title": t, "snippet": "…"} for t in titles]}}


def entity_payload(ids: list[str]) -> dict:
    return {
        "entities": {
            "Q25188": {
                "claims": {
                    "P136": [
                        {
                            "mainsnak": {
                                "datavalue": {
                                    "type": "wikibase-entityid",
                                    "value": {"id": item, "title": item},
                                }
                            },
                            "rank": "normal",
                        }
                        for item in ids
                    ]
                }
            }
        }
    }


def labels_payload(mapping: dict[str, str]) -> dict:
    return {
        "entities": {
            item: {"labels": {"en": {"language": "en", "value": value}}}
            for item, value in mapping.items()
        }
    }


def parse_payload(wikitext: str) -> dict:
    return {"parse": {"title": "Inception (2007 film)", "wikitext": wikitext}}


class WikiNetwork:
    """Dispatches every MediaWiki/Wikidata call to the test's own handler."""

    def __init__(self, mock, cache_dir):
        self.mock = mock
        self.cache_dir = cache_dir
        self.hits: list[httpx.URL] = []
        self.handler = None

    def calls(self, *, action: str | None = None) -> list[httpx.URL]:
        if action is None:
            return list(self.hits)
        return [u for u in self.hits if u.params.get("action") == action]

    def srsearches(self) -> list[str]:
        return [
            u.params.get("srsearch", "")
            for u in self.hits
            if u.params.get("list") == "search"
        ]

    def cache_files(self) -> list:
        return list(self.cache_dir.glob("*.json")) if self.cache_dir.exists() else []


@pytest.fixture
def wiki(monkeypatch, tmp_path) -> WikiNetwork:
    """respx-backed stub with the wiki cache pointed at ``tmp_path``."""
    monkeypatch.setattr(wikipedia, "_CACHE_DIR", tmp_path / "wiki")
    mock = respx.mock(assert_all_called=False)
    mock.start()
    net = WikiNetwork(mock, tmp_path / "wiki")

    def dispatch(request: httpx.Request) -> httpx.Response:
        assert net.handler is not None, "test did not install a handler"
        net.hits.append(request.url)
        return net.handler(request)

    for pattern in (
        r"https://en\.wikipedia\.org/w/api\.php",
        r"https://www\.wikidata\.org/w/api\.php",
        r"https://www\.wikidata\.org/wiki/Special:EntityData/.*",
    ):
        mock.get(url__regex=pattern).mock(side_effect=dispatch)
    try:
        yield net
    finally:
        mock.stop()


def test_enrich_movie_fills_overview_genres_runtime(wiki):
    """A WAF-blocked IMDb page still yields a synopsis, genres, and a runtime."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if request.url.host == "www.wikidata.org":
            if request.url.path.startswith("/wiki/Special:EntityData"):
                return httpx.Response(200, json=entity_payload(["Q496523", "Q10574855"]))
            return httpx.Response(
                200,
                json=labels_payload(
                    {"Q496523": "Science fiction film", "Q10574855": "Heist film"}
                ),
            )
        if params.get("action") == "parse":
            return httpx.Response(200, json=parse_payload(INCEPTION_WIKITEXT))
        return httpx.Response(
            200, json=pages_payload("Inception", INCEPTION_INTRO, "Q25188")
        )

    wiki.handler = handler
    result = wikipedia.enrich_movie(cfg(), "Inception", 2007)
    assert result["overview"].startswith("Inception (also known as")
    # Wikidata labels are item names; the genre row wants the genre itself.
    assert result["genres"] == ["Science fiction", "Heist"]
    assert result["runtime"] == 148


def test_person_page_hazard_falls_back_to_the_film_article(wiki):
    """"Oppenheimer" resolves to the physicist; the film/movie guard rejects
    that page and the year-tagged search finds the film article instead."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("list") == "search":
            assert params.get("srsearch") == "Oppenheimer (2025) film"
            return httpx.Response(
                200, json=search_payload(["Oppenheimer (2025 film)"])
            )
        title = params.get("titles", "")
        if title == "Oppenheimer (2025 film)":
            return httpx.Response(
                200, json=pages_payload(title, OPPENHEIMER_FILM, "Q124784200")
            )
        return httpx.Response(200, json=pages_payload(title, OPPENHEIMER_PERSON, "Q10668671"))

    wiki.handler = handler
    result = wikipedia.enrich_movie(cfg(), "Oppenheimer", 2025)
    assert result["overview"].startswith("Oppenheimer is a 2025")
    assert "physicist" not in result["overview"]
    assert wiki.srsearches() == ["Oppenheimer (2025) film"]


def test_no_wikibase_item_keeps_genres_empty(wiki):
    """An article without a Wikidata item still provides overview and runtime."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.wikidata.org":
            raise AssertionError("no Wikidata call without a Q-id")
        if request.url.params.get("action") == "parse":
            return httpx.Response(200, json=parse_payload(INCEPTION_WIKITEXT))
        return httpx.Response(
            200, json=pages_payload("Inception", INCEPTION_INTRO, None)
        )

    wiki.handler = handler
    result = wikipedia.enrich_movie(cfg(), "Inception", 2007)
    assert result["genres"] == []
    assert result["overview"].startswith("Inception (also known as")
    assert result["runtime"] == 148


def test_all_lookups_failing_returns_empty_fields(wiki):
    """Every endpoint 500ing must degrade to today's payload, not raise."""
    wiki.handler = lambda request: httpx.Response(500, json={})
    result = wikipedia.enrich_movie(cfg(), "Inception", 2007)
    assert result == {"overview": "", "genres": [], "runtime": None}
    assert wiki.cache_files() == [], "failures must not be cached for a day"


def test_warm_cache_avoids_a_second_roundtrip(wiki):
    """The second visit for the same (title, year) comes from disk."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.wikidata.org":
            if request.url.path.startswith("/wiki/Special:EntityData"):
                return httpx.Response(200, json=entity_payload(["Q496523"]))
            return httpx.Response(
                200, json=labels_payload({"Q496523": "Science fiction film"})
            )
        if request.url.params.get("action") == "parse":
            return httpx.Response(200, json=parse_payload(INCEPTION_WIKITEXT))
        return httpx.Response(
            200, json=pages_payload("Inception", INCEPTION_INTRO, "Q25188")
        )

    wiki.handler = handler
    first = wikipedia.enrich_movie(cfg(), "Inception", 2007)
    network_calls = len(wiki.hits)
    second = wikipedia.enrich_movie(cfg(), "Inception", 2007)
    assert network_calls > 0
    assert len(wiki.hits) == network_calls, "cached visit must not hit the network"
    assert second == first
    assert len(wiki.cache_files()) == 1


def test_partial_success_keeps_the_available_fields(wiki):
    """A failing parse call costs the runtime only."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={})
        if request.url.params.get("action") == "parse":
            return httpx.Response(500, json={})
        return httpx.Response(
            200, json=pages_payload("Inception", INCEPTION_INTRO, "Q25188")
        )

    wiki.handler = handler
    result = wikipedia.enrich_movie(cfg(), "Inception", 2007)
    assert result["runtime"] is None
    assert result["overview"].startswith("Inception (also known as")


def test_missing_article_degrades_without_a_year_query(wiki):
    """A title with no article at all degrades to empty fields, no year in search."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("list") == "search":
            return httpx.Response(200, json=search_payload([]))
        return httpx.Response(
            200, json={"query": {"pages": [{"title": "Obscure", "missing": ""}]}}
        )

    wiki.handler = handler
    result = wikipedia.enrich_movie(cfg(), "Obscure")
    assert result == {"overview": "", "genres": [], "runtime": None}
    assert wiki.srsearches() == ["Obscure film"]
