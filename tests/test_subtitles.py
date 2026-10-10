from __future__ import annotations

import io
import zipfile

import pytest

from arr.subtitles import SubtitleCandidate, rank_candidates
from arr.subtitles.base import SubtitleError
from arr.subtitles.subscene import SubsceneClient, _extract_srt, is_valid_subtitle_payload
from arr.subtitles.yify import YifySubtitlesClient


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


def test_extract_srt_valid_zip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sub.srt", "1\n00:00:01,000 --> 00:00:04,000\nHello world\n")
    data = buf.getvalue()
    out = _extract_srt(data)
    assert b"Hello world" in out


def test_extract_srt_corrupt_zip():
    bad_zip = b"PK\x03\x04corrupteddata"
    with pytest.raises(SubtitleError, match="Corrupt subtitle ZIP archive"):
        _extract_srt(bad_zip)


def test_extract_srt_rejects_html():
    html = (
        b"<!DOCTYPE html><html><head><title>404 Not Found</title></head>"
        b"<body>Error</body></html>"
    )
    with pytest.raises(SubtitleError, match="received HTML instead of subtitle"):
        _extract_srt(html)


def test_extract_srt_rejects_invalid_text():
    garbage = b"Random binary data or text without subtitle format"
    with pytest.raises(SubtitleError, match="not a valid subtitle"):
        _extract_srt(garbage)


def test_is_valid_subtitle_payload():
    assert is_valid_subtitle_payload(b"WEBVTT\n\n00:01.000 --> 00:04.000\nTest")
    ass_header = b"[Script Info]\nTitle: Test\nDialogue: 0,0:00:01.00,0:00:04.00"
    assert is_valid_subtitle_payload(ass_header)
    assert not is_valid_subtitle_payload(b"<html><body>Download here</body></html>")
    assert not is_valid_subtitle_payload(b"")


def test_subscene_download_follows_intermediate_page():
    class FakeSession:
        def get(self, url, timeout=20):
            if url == "https://subscene.com/subtitles/inception-123":
                class Resp:
                    status_code = 200
                    text = (
                        '<html><body><a id="downloadButton" '
                        'href="/subtitles/download/inception-123">Download</a></body></html>'
                    )
                    content = text.encode()
                return Resp()
            if url == "https://subscene.com/subtitles/download/inception-123":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z:
                    z.writestr("test.srt", "1\n00:00:01,000 --> 00:00:04,000\nTest\n")
                class RespZip:
                    status_code = 200
                    content = buf.getvalue()
                return RespZip()
            raise ValueError(f"Unexpected url {url}")

    client = SubsceneClient(session=FakeSession())
    cand = SubtitleCandidate(
        subtitle_id=1, file_id=1, language="en", release_name="Inception",
        downloads=10, hearing_impaired=False, hd=True, upload_date="",
        download_link="https://subscene.com/subtitles/inception-123",
    )
    data = client.download(cand)
    assert b"Test" in data


def test_yify_download_follows_intermediate_page():
    class FakeSession:
        def get(self, url, timeout=20):
            if url == "https://yifysubtitles.ch/subtitle/inception-777":
                class Resp:
                    status_code = 200
                    text = (
                        '<html><body><a class="download-subtitle" '
                        'href="/subtitle/inception-777.zip">Download</a></body></html>'
                    )
                    content = text.encode()
                return Resp()
            if url == "https://yifysubtitles.ch/subtitle/inception-777.zip":
                buf = io.BytesIO()
                with zipfile.ZipFile(buf, "w") as z:
                    z.writestr("inception.srt", "1\n00:00:01,000 --> 00:00:04,000\nInception sub\n")
                class RespZip:
                    status_code = 200
                    content = buf.getvalue()
                return RespZip()
            raise ValueError(f"Unexpected url {url}")

    client = YifySubtitlesClient(session=FakeSession())
    cand = SubtitleCandidate(
        subtitle_id=777, file_id=777, language="en", release_name="Inception",
        downloads=10, hearing_impaired=False, hd=True, upload_date="",
        download_link="https://yifysubtitles.ch/subtitle/inception-777",
    )
    data = client.download(cand)
    assert b"Inception sub" in data
