import httpx
import pytest
import respx

from arr.subtitles import (
    OpenSubtitlesClient,
    SubtitleCandidate,
    rank_candidates,
)


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


def test_forced_only_filters():
    cands = [mk(1, 1000, False, "A", "2024-01-01"), mk(2, 5, True, "A", "2024-01-01")]
    ranked = rank_candidates(cands, release_name="A", forced_only=True)
    assert [c.subtitle_id for c in ranked] == [2]


def test_client_requires_key():
    with pytest.raises(Exception):
        OpenSubtitlesClient("")


def test_client_search_maps_candidates():
    payload = {
        "data": [
            {
                "id": "7",
                "attributes": {
                    "language": "en",
                    "release": "My.Show.S01E01",
                    "download_count": 42,
                    "hearing_impaired": True,
                    "hd": True,
                    "upload_date": "2024-01-01",
                    "files": [{"file_id": 99, "file_name": "x.srt"}],
                },
            }
        ]
    }
    with respx.mock:
        respx.get("https://api.opensubtitles.com/api/v1/subtitles").mock(
            return_value=httpx.Response(200, json=payload)
        )
        c = OpenSubtitlesClient("k")
        out = c.search(imdb_id="tt1", season=1, episode=2, languages=["en"])
    assert len(out) == 1
    assert out[0].file_id == 99
    assert out[0].downloads == 42
    assert out[0].hearing_impaired
