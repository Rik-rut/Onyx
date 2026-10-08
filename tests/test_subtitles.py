from arr.subtitles import SubtitleCandidate, rank_candidates


def mk(rid, downloads, hi, rel, date):
    return SubtitleCandidate(
        subtitle_id=rid,
        file_id=rid,
        language="en",
        release_name=rel,
        downloads=downloads,
        hearing_impaired=hi,
        hd=True,
        upload_date=date,
    )


def test_rank_prefers_hearing_impaired_match():
    cands = [
        mk(1, 1000, False, "My.Show.S01E01.1080p", "2024-01-01"),
        mk(2, 10, True, "My.Show.S01E01.1080p", "2024-01-01"),
    ]
    ranked = rank_candidates(cands, release_name="My.Show.S01E01.1080p")
    assert ranked[0].subtitle_id == 2


def test_rank_then_download_count():
    cands = [
        mk(1, 50, False, "A", "2024-01-01"),
        mk(2, 500, False, "A", "2024-01-01"),
    ]
    ranked = rank_candidates(cands, release_name="A")
    assert ranked[0].subtitle_id == 2


def test_rank_then_release_similarity():
    cands = [
        mk(1, 10, False, "Unrelated.Release.Name", "2024-01-01"),
        mk(2, 10, False, "My.Show.S01E01.1080p", "2024-01-01"),
    ]
    ranked = rank_candidates(cands, release_name="My.Show.S01E01.1080p")
    assert ranked[0].subtitle_id == 2


def test_forced_only_filters():
    cands = [mk(1, 1000, False, "A", "2024-01-01"), mk(2, 5, True, "A", "2024-01-01")]
    ranked = rank_candidates(cands, release_name="A", forced_only=True)
    assert [c.subtitle_id for c in ranked] == [2]


def test_forced_only_empty_when_none_match():
    cands = [mk(1, 1000, False, "A", "2024-01-01")]
    assert rank_candidates(cands, release_name="A", forced_only=True) == []
