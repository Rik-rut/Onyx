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


def test_addic7ed_search_and_download():
    from arr.subtitles.addic7ed import Addic7edClient

    search_html = """
    <html><body>
    <a href="/serie/Breaking_Bad/1/1/Pilot">Breaking Bad - 01x01 - Pilot</a>
    </body></html>
    """

    episode_html = """
    <html><body>
    <table class="tabel95">
        <tr><td class="NewsTitle">Version 720p HDTV, Duration: 48.00</td></tr>
        <tr>
            <td class="language">English</td>
            <td>123 Downloads</td>
            <td><a href="/updated/1/6159/1">Most Updated</a></td>
        </tr>
    </table>
    </body></html>
    """

    srt_bytes = b"1\r\n00:00:01,000 --> 00:00:04,000\nHello from Addic7ed\n"

    class FakeSession:
        def get(self, url, timeout=20, headers=None):
            class Resp:
                def __init__(self, text, content, status_code=200):
                    self.text = text
                    self.content = content
                    self.status_code = status_code

            if "search.php" in url:
                return Resp(search_html, search_html.encode())
            if "/serie/Breaking_Bad/1/1/Pilot" in url:
                return Resp(episode_html, episode_html.encode())
            if "/updated/1/6159/1" in url:
                return Resp("", srt_bytes)
            raise ValueError(f"Unexpected url {url}")

    client = Addic7edClient(session=FakeSession())
    cands = client.search(title="Breaking Bad (2008)", season=1, episode=1, languages=["en"])
    assert len(cands) == 1
    c = cands[0]
    assert c.language == "en"
    assert "Breaking Bad S01E01 720p HDTV" in c.release_name
    assert c.downloads == 123
    assert c.download_link == "https://www.addic7ed.com/updated/1/6159/1"

    data = client.download(c)
    assert b"Hello from Addic7ed" in data


def test_subdl_search_and_download():
    from arr.subtitles.subdl import SubdlClient

    no_key_client = SubdlClient(api_key="")
    assert no_key_client.search(title="Inception") == []

    class FakeSession:
        def get(self, url, timeout=20, headers=None):
            class Resp:
                status_code = 200

                def json(self):
                    return {
                        "status": True,
                        "subtitles": [
                            {
                                "release_name": "Inception.2010.1080p",
                                "lang": "English",
                                "url": "/subtitles/123.srt",
                                "download_count": 55,
                                "hi": True,
                            }
                        ],
                    }

                content = b"1\n00:00:01,000 --> 00:00:03,000\nSubDL sub\n"

            return Resp()

    client = SubdlClient(api_key="testkey", session=FakeSession())
    cands = client.search(title="Inception", languages=["en"])
    assert len(cands) == 1
    assert cands[0].release_name == "Inception.2010.1080p"
    assert cands[0].hearing_impaired is True
    assert cands[0].download_link == "https://dl.subdl.com/subtitles/123.srt"

    data = client.download(cands[0])
    assert b"SubDL sub" in data


def test_ensure_subtitles_embedded_detected(tmp_path, monkeypatch):
    from arr.config.settings import Config
    from arr.db import DB
    from arr.subtitles.service import ensure_subtitles

    media = tmp_path / "movie.mkv"
    media.write_bytes(b"\x00" * 1024)

    db = DB(tmp_path / "test.db")
    cfg = Config()

    monkeypatch.setattr(
        "arr.subtitles.service.has_embedded_subtitles",
        lambda p, lang: True,
    )

    res = ensure_subtitles(media, cfg=cfg, db=db, release_name="Movie")
    assert len(res) == 1
    assert res[0]["source"] == "embedded"
    assert res[0]["state"] == "ok"
    assert res[0]["path"] == str(media)

    subs = db.list_subtitles(str(media))
    assert len(subs) == 1
    assert subs[0]["source"] == "embedded"
    assert subs[0]["state"] == "ok"
    db.close()


def test_ensure_subtitles_tv_falls_back_to_addic7ed(tmp_path, monkeypatch):
    from arr.config.settings import Config
    from arr.db import DB
    from arr.subtitles.base import SubtitleCandidate
    from arr.subtitles.service import ensure_subtitles

    media = tmp_path / "Show - S01E01.mkv"
    media.write_bytes(b"\x00" * 1024)

    db = DB(tmp_path / "test.db")
    cfg = Config()

    monkeypatch.setattr("arr.subtitles.service.has_embedded_subtitles", lambda p, lang: False)

    fake_cand = SubtitleCandidate(
        subtitle_id=888,
        file_id=888,
        language="en",
        release_name="Show S01E01 720p",
        downloads=100,
        hearing_impaired=False,
        hd=True,
        upload_date="",
        download_link="http://example.com/sub.srt",
    )

    class FakeAddic7ed:
        def search(self, **kwargs):
            return [fake_cand]

        def download(self, cand):
            return b"1\n00:00:01,000 --> 00:00:02,000\nTV sub\n"

    monkeypatch.setattr("arr.subtitles.service.Addic7edClient", lambda base: FakeAddic7ed())

    res = ensure_subtitles(
        media, cfg=cfg, db=db, season=1, episode=1, release_name="Show S01E01"
    )
    assert len(res) == 1
    assert res[0]["source"] == "addic7ed"
    assert res[0]["state"] == "ok"
    srt_file = tmp_path / "Show - S01E01.en.srt"
    assert srt_file.exists()
    assert srt_file.read_bytes() == b"1\n00:00:01,000 --> 00:00:02,000\nTV sub\n"
    db.close()

