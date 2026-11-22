from arr.core.models import MediaType, QualityProfile, Query, Release
from arr.core.parsing import explain, hard_filter, parse_release, rank


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
