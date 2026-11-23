from arr.core.models import MediaType, QualityProfile, Query, Release
from arr.core.parsing import enrich_release, explain, hard_filter, parse_release, rank


def mk(title, seeds=10, size_mb=2000, indexer="yts", **kw):
    return Release(
        indexer=indexer,
        title=title,
        infohash=kw.pop("infohash", title[:40].ljust(40, "0")),
        magnet=f"magnet:?xt=urn:btih:{title[:40]}",
        media_type=kw.pop("media_type", MediaType.MOVIE),
        seeds=seeds,
        peers=kw.pop("peers", 5),
        size_bytes=size_mb * 1024 * 1024,
        **kw,
    )


def test_parse_movie_title():
    p = parse_release("Inception.2010.1080p.BluRay.x265-GROUP")
    assert p["title"] == "Inception"
    assert p["year"] == 2010
    assert p["resolution"] == "1080p"
    assert p["source"] == "BluRay"
    assert p["codec"] == "HEVC"


def test_parse_tv_episode():
    p = parse_release("Breaking.Bad.S05E14.1080p.WEB-DL.x264-NTb")
    assert p["season"] == 5
    assert p["episode"] == 14
    assert p["source"] == "WEB-DL"


def test_parse_season_pack():
    p = parse_release("Breaking.Bad.S05.COMPLETE.1080p.BluRay.x265")
    assert p["is_pack"] is True


def test_hard_filter_rejects_cam():
    cfg = {"min_seeders": 1, "resolutions": ["1080p"]}
    q = Query(media_type=MediaType.MOVIE, text="x")
    r = mk("Some.Movie.2020.CAM.1080p", seeds=50)
    rank([r], q, QualityProfile(), cfg)
    assert "CAM" in (hard_filter(r, q, QualityProfile(), cfg) or "") or _rejected(r, q, cfg)


def _rejected(r, q, cfg):
    s = rank([r], q, QualityProfile(), cfg)[0]
    return s.rejected is not None


def test_min_seeders():
    q = Query(media_type=MediaType.MOVIE)
    cfg = {"min_seeders": 5}
    r = mk("Inception.2010.1080p.BluRay.x265", seeds=2)
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is not None


def test_rank_stable_and_deterministic():
    titles = [
        ("Movie A 2020 1080p WEB-DL x265", 50, 1500),
        ("Movie A 2020 1080p BluRay x265", 50, 2000),
        ("Movie A 2020 2160p BluRay x265", 50, 8000),
        ("Movie A 2020 720p HDTV x264", 60, 900),
        ("Movie A 2020 1080p WEB-DL x264", 40, 1200),
    ]
    cfg = {"min_seeders": 1, "resolutions": ["2160p", "1080p", "720p"]}
    q = Query(media_type=MediaType.MOVIE)
    rels = [mk(t, seeds=s, size_mb=z, infohash=t[:40].ljust(40, "0")) for t, s, z in titles]

    def ordered(rels):
        return [
            x.release.infohash
            for x in rank(list(rels), q, QualityProfile(), cfg)
            if x.rejected is None
        ]

    first = ordered(rels)
    for _ in range(3):
        assert ordered(rels) == first
    # highest seeders first
    assert first[0].startswith("Movie A 2020 720p")


def test_tv_episode_mismatch_rejected():
    q = Query(media_type=MediaType.TV, season=1, episode=2)
    cfg = {"min_seeders": 1}
    r = mk("Show.S01E03.1080p.WEB-DL.x264", media_type=MediaType.TV, season=1, episode=3)
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is not None


def test_season_pack_allowed_for_season_scope():
    q = Query(media_type=MediaType.TV, season=1)
    cfg = {"min_seeders": 1, "prefer_season_packs": True}
    r = mk("Show.S01.1080p.WEB-DL.x264", media_type=MediaType.TV, season=1, is_pack=True)
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is None


def test_explain_output():
    q = Query(media_type=MediaType.MOVIE)
    cfg = {"min_seeders": 1}
    r = mk("Movie.2020.1080p.BluRay.x265", seeds=3)
    ex = explain(rank([r], q, QualityProfile(), cfg))
    assert "seeders=3" in ex


def test_title_mismatch_rejected_for_strict_indexer():
    """EZTV returns unrelated latest torrents; the title gate must reject them."""
    q = Query(media_type=MediaType.TV, text="zzzznotarealshowzzz")
    cfg = {"min_seeders": 1, "title_strict_indexers": ["eztv"]}
    r = mk(
        "Some.Other.Show.S01E01.1080p.WEB-DL.x264",
        media_type=MediaType.TV, indexer="eztv",
    )
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is not None
    assert "does not match" in s.rejected


def test_title_match_passes_strict_indexer():
    q = Query(media_type=MediaType.TV, title="Game of Thrones")
    cfg = {"min_seeders": 1, "title_strict_indexers": ["eztv"]}
    r = mk(
        "Game.of.Thrones.S01E01.1080p.WEB-DL.x264",
        media_type=MediaType.TV, indexer="eztv",
    )
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is None


def test_title_gate_only_applies_to_configured_indexers():
    """Nyaa romanized anime titles must not be rejected by the title gate."""
    q = Query(media_type=MediaType.TV, text="Kimi no Na wa")
    cfg = {"min_seeders": 1, "title_strict_indexers": ["eztv"]}
    r = mk(
        "Your Name (2016) [1080p] [BluRay]",
        media_type=MediaType.TV, indexer="nyaa",
    )
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is None


def test_primary_indexer_beats_fallback_with_more_seeders():
    """2.1: primary-indexer release beats fallback release with more seeders."""
    q = Query(media_type=MediaType.TV, text="Breaking Bad")
    cfg = {
        "min_seeders": 1,
        "indexer_priority": ["eztv", "tpb"],
    }
    eztv_release = mk("Breaking.Bad.S01E01.1080p.WEB-DL", seeds=5, indexer="eztv")
    tpb_release = mk("Breaking.Bad.S01E01.1080p.WEB-DL", seeds=50, indexer="tpb")
    scored = rank([tpb_release, eztv_release], q, QualityProfile(), cfg)
    assert scored[0].release.indexer == "eztv"
    assert scored[1].release.indexer == "tpb"


def test_fallback_wins_when_primary_empty():
    """2.1: fallback wins when primary set is empty."""
    q = Query(media_type=MediaType.TV, text="Breaking Bad")
    cfg = {
        "min_seeders": 1,
        "indexer_priority": ["eztv", "tpb"],
    }
    tpb_release = mk("Breaking.Bad.S01E01.1080p.WEB-DL", seeds=50, indexer="tpb")
    scored = rank([tpb_release], q, QualityProfile(), cfg)
    assert scored[0].release.indexer == "tpb"


def test_unknown_indexer_sorts_last():
    """2.1: unknown indexer sorts last regardless of seeders."""
    q = Query(media_type=MediaType.MOVIE, text="Inception")
    cfg = {
        "min_seeders": 1,
        "indexer_priority": ["yts", "unknown-ish"],
    }
    yts_release = mk("Inception 2010 1080p", seeds=5, indexer="yts")
    unknown_release = mk("Inception 2010 1080p", seeds=100, indexer="unknown-ish")
    scored = rank([unknown_release, yts_release], q, QualityProfile(), cfg)
    assert scored[0].release.indexer == "yts"
    assert scored[1].release.indexer == "unknown-ish"


def test_custom_priority_order_respected():
    """2.1: custom priority order is respected."""
    q = Query(media_type=MediaType.TV, text="Show")
    cfg = {
        "min_seeders": 1,
        "indexer_priority": ["tpb", "nyaa", "eztv", "yts"],
    }
    releases = [
        mk("Show S01E01", seeds=10, indexer="yts"),
        mk("Show S01E01", seeds=20, indexer="eztv"),
        mk("Show S01E01", seeds=30, indexer="nyaa"),
        mk("Show S01E01", seeds=40, indexer="tpb"),
    ]
    scored = rank(releases, q, QualityProfile(), cfg)
    assert [s.release.indexer for s in scored] == ["tpb", "nyaa", "eztv", "yts"]


def test_rank_stable_with_indexer_priority():
    """2.1: rank remains stable and deterministic with indexer priority."""
    q = Query(media_type=MediaType.MOVIE, text="Movie")
    cfg = {
        "min_seeders": 1,
        "indexer_priority": ["yts", "eztv"],
    }
    releases = [
        mk("Movie 2020 720p", seeds=10, indexer="yts"),
        mk("Movie 2020 720p", seeds=10, indexer="eztv"),
    ]
    scored = rank(releases, q, QualityProfile(), cfg)
    assert scored[0].release.indexer == "yts"
    assert scored[1].release.indexer == "eztv"


BAD_NYAA_TITLE = (
    "[DB] Kimetsu no Yaiba | Demon Slayer: Kimetsu no Yaiba (Season 1+2+3+4+5+Movie) "
    "[Dual Audio 10bit BD1080p][HEVC-x265][BDRip][Sub-Eng-Chi-Jap]-ANiGMA"
)


def test_parse_known_bad_nyaa_title_yields_string_fields():
    """1.1: guessit's list-typed release_group must not leak past the parse boundary."""
    p = parse_release(BAD_NYAA_TITLE)
    assert isinstance(p["group"], str)
    # rank() completes without raising, whatever the verdict is
    r = mk(BAD_NYAA_TITLE, media_type=MediaType.TV)
    q = Query(media_type=MediaType.TV, text="demon slayer")
    cfg = {"min_seeders": 0, "resolutions": ["2160p", "1080p", "720p"], "title_strict_indexers": []}
    out = rank([r], q, QualityProfile(), cfg)
    assert len(out) == 1
    assert out[0].release.group is None or isinstance(out[0].release.group, str)
    # The raw name is preserved for the drawer's coverage display.
    assert out[0].release.raw_title == BAD_NYAA_TITLE


def test_rank_completes_with_list_typed_fields():
    """1.2: values smuggled in as lists (pydantic v2 does not validate on assignment)
    must not crash _is_bad or rank."""
    r = mk("Show S01E01 1080p WEB x264", media_type=MediaType.TV)
    r.group = ["GroupA", "GroupB"]  # type: ignore[assignment]
    r.source = ["WEB", "HDTV"]  # type: ignore[assignment]
    q = Query(media_type=MediaType.TV, season=1, episode=1)
    cfg = {"min_seeders": 0, "resolutions": ["1080p"], "title_strict_indexers": []}
    out = rank([r], q, QualityProfile(), cfg)
    assert len(out) == 1
    assert out[0].release is r


def test_pack_wrong_season_rejected():
    """2.3: an S03 pack is rejected for a season=2 query."""
    r = mk("Show.S03.COMPLETE.1080p.BluRay.x264", media_type=MediaType.TV)
    q = Query(media_type=MediaType.TV, text="Show", season=2)
    cfg = {"min_seeders": 0, "resolutions": ["1080p"], "title_strict_indexers": []}
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is not None and "pack season" in s.rejected


def test_pack_matching_season_accepted():
    """2.3: an S02 pack is accepted for a season=2 query."""
    r = mk("Show.S02.COMPLETE.1080p.BluRay.x264", media_type=MediaType.TV)
    q = Query(media_type=MediaType.TV, text="Show", season=2)
    cfg = {"min_seeders": 0, "resolutions": ["1080p"], "title_strict_indexers": []}
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is None


def test_packs_rejected_when_excluded():
    """2.3: the endpoint's single-episode contract (exclude_packs) drops even
    in-season packs."""
    r = mk("Show.S02.COMPLETE.1080p.BluRay.x264", media_type=MediaType.TV)
    q = Query(media_type=MediaType.TV, text="Show", season=2, episode=5, exclude_packs=True)
    cfg = {"min_seeders": 0, "resolutions": ["1080p"], "title_strict_indexers": []}
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is not None and "pack" in s.rejected


def test_per_episode_query_without_flag_keeps_packs():
    """Monitor-flow guard: _enqueue_episodes queries carry season+episode but must
    still see season packs (prefer_season_packs depends on it)."""
    r = mk("Show.S02.COMPLETE.1080p.BluRay.x264", media_type=MediaType.TV)
    q = Query(media_type=MediaType.TV, text="Show", season=2, episode=5)
    cfg = {"min_seeders": 0, "resolutions": ["1080p"], "title_strict_indexers": []}
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is None


def test_anime_query_skips_se_gate():
    """2.3: an anime query accepts a release with no SxxExx designation at all
    (NYAA titles carry global episode numbers, not seasons)."""
    r = mk("Naruto 215 1080p", media_type=MediaType.TV)
    q = Query(media_type=MediaType.TV, text="Naruto", season=1, episode=2, anime=True)
    cfg = {"min_seeders": 0, "resolutions": ["1080p"], "title_strict_indexers": []}
    s = rank([r], q, QualityProfile(), cfg)[0]
    assert s.rejected is None


# ---------------- anime release scoping (fix-movie-metadata-anime-scoping) ----------------

ANIME_CFG = {"min_seeders": 0, "resolutions": ["1080p"], "title_strict_indexers": []}


def _anime_query(**kw):
    return Query(
        media_type=MediaType.TV,
        text="Demon Slayer",
        season=kw.pop("season", 1),
        episode=kw.pop("episode", None),
        anime=True,
        **kw,
    )


def _ranked(r, q, cfg=None):
    return rank([r], q, QualityProfile(), cfg or ANIME_CFG)[0]


def test_parse_carries_release_type():
    """guessit's movie/episode distinction must survive the parse boundary."""
    movie = parse_release(
        "Demon Slayer -Kimetsu no Yaiba- The Movie - Infinity Castle (2025) 1080p"
    )
    assert movie["type"] == "movie"
    episode = parse_release("Demon Slayer -Kimetsu no Yaiba- 045 [1080p]")
    assert episode["episode"] == 45
    assert episode["type"] == "episode"


def test_enrich_release_carries_type():
    """The ranker sees the type, so it can scope without indexer help."""
    r = Release(
        indexer="nyaa",
        title="Demon Slayer -Kimetsu no Yaiba- The Movie - Infinity Castle (2025) 1080p",
        infohash="0" * 40,
        magnet="magnet:?xt=urn:btih:" + "0" * 40,
        media_type=MediaType.TV,
    )
    assert enrich_release(r).release_type == "movie"


def test_anime_query_rejects_theatrical_movie_release():
    """The Infinity Castle movie must never sit in an episode's release list."""
    r = mk(
        "Demon Slayer -Kimetsu no Yaiba- The Movie - Infinity Castle (2025) 1080p",
        media_type=MediaType.TV,
    )
    s = _ranked(r, _anime_query(episode=1))
    assert s.rejected is not None and "anime movie release" in s.rejected


def test_anime_release_tagged_to_other_season_rejected():
    """A release carrying an explicit S5 token is out of scope for season 1."""
    r = mk(
        "[Salieri] Demon Slayer -Kimetsu no Yaiba- S5 - Hashira Training Arc (1080p)",
        media_type=MediaType.TV,
    )
    s = _ranked(r, _anime_query(episode=1))
    assert s.rejected is not None and "release season 5" in s.rejected


def test_anime_pack_without_requested_season_rejected():
    """An S4+S5 pack does not cover the requested season."""
    r = mk("[Tenrai-Sensei] Demon Slayer -Kimetsu no Yaiba- S4+S5 (1080p)", media_type=MediaType.TV)
    s = _ranked(r, _anime_query(episode=1))
    assert s.rejected is not None and "do not cover 1" in s.rejected


def test_anime_pack_covering_requested_season_passes():
    """The Season 1-4 + Movie pack does cover season 1, so it stays offered."""
    r = mk("Demon Slayer -Kimetsu no Yaiba- Season 1-4 + Movie [1080p]", media_type=MediaType.TV)
    q = _anime_query(season=2)
    assert _ranked(r, q).rejected is None


def test_anime_bare_number_outside_scope_rejected():
    """Episode 45 is outside the requested scope when numbering is trusted."""
    r = mk("Demon Slayer -Kimetsu no Yaiba- 045 [1080p]", media_type=MediaType.TV)
    q = _anime_query(episode=1, anime_number_match=[1])
    s = _ranked(r, q)
    assert s.rejected is not None and "outside requested scope" in s.rejected


def test_anime_bare_number_in_scope_passes():
    r = mk("Demon Slayer -Kimetsu no Yaiba- 001 (1080p) [SubsPlease]", media_type=MediaType.TV)
    q = _anime_query(episode=1, anime_number_match=[1])
    assert _ranked(r, q).rejected is None


def test_anime_unnumbered_release_survives_number_filter():
    """Number matching only applies to releases that carry a number."""
    r = mk("Demon Slayer -Kimetsu no Yaiba- Season 1-4 + Movie [1080p]", media_type=MediaType.TV)
    q = _anime_query(episode=1, anime_number_match=[1])
    assert _ranked(r, q).rejected is None


def test_anime_number_filter_inert_when_unset():
    """Locally-numbered shows (Demon Slayer S2+) keep title-based results."""
    r = mk("Demon Slayer -Kimetsu no Yaiba- 045 [1080p]", media_type=MediaType.TV)
    q = _anime_query(season=2)
    assert q.anime_number_match is None
    assert _ranked(r, q).rejected is None


def test_anime_bare_number_not_scoped_as_a_season():
    """"Naruto 215" is global episode 215; guessit's S02E15 reading of that
    number must not scope the release out of a season-1 query."""
    r = mk("Naruto 215 1080p", media_type=MediaType.TV)
    q = Query(
        media_type=MediaType.TV, text="Naruto", season=1, episode=2, anime=True
    )
    assert _ranked(r, q).rejected is None


def test_western_gate_outcomes_unchanged():
    """The new anime branch must not move a single Western TV outcome."""
    wrong = mk("Breaking.Bad.S05E14.1080p.WEB-DL.x264", media_type=MediaType.TV)
    q = Query(media_type=MediaType.TV, text="Breaking Bad", season=2, episode=14)
    s = _ranked(wrong, q)
    assert s.rejected is not None and "season 5 != 2" in s.rejected

    right = mk("Breaking.Bad.S02E14.1080p.WEB-DL.x264", media_type=MediaType.TV)
    assert _ranked(right, q).rejected is None

    # A movie-typed name is not rejected for being a movie on a Western query.
    movie_like = mk("Inception.2010.1080p.BluRay.x265", media_type=MediaType.TV)
    assert _ranked(movie_like, q).rejected is None
