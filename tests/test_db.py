import time

from arr.core.models import DownloadState
from arr.db import DB


def test_download_add_dedupe(tmp_path):
    db = DB(tmp_path / "arr.db")
    assert db.add_download("h1", media_type="movie", title="X") is True
    assert db.add_download("h1", media_type="movie", title="X") is False
    db.close()


def test_download_state_transition(tmp_path):
    db = DB(tmp_path / "arr.db")
    db.add_download("h2", media_type="movie")
    db.set_download_state("h2", DownloadState.DOWNLOADING)
    d = db.get_download("h2")
    assert d["state"] == "downloading"
    db.close()


def test_download_prefix_and_case_insensitive(tmp_path):
    db = DB(tmp_path / "arr.db")
    db.add_download(
        "b6abea6bac7debb9bcf845983727fa6edfced29d",
        media_type="movie",
        title="Spider-Man",
    )
    # Exact match
    assert db.get_download("b6abea6bac7debb9bcf845983727fa6edfced29d") is not None
    # Case-insensitive
    assert db.get_download("B6ABEA6BAC7DEBB9BCF845983727FA6EDFCED29D") is not None
    # Prefix match (8 chars as in table)
    prefix_match = db.get_download("b6abea6b")
    assert prefix_match is not None
    assert prefix_match["title"] == "Spider-Man"
    # Case-insensitive prefix
    assert db.get_download("B6ABEA6B") is not None
    # Non-existent
    assert db.get_download("nonexistent") is None
    db.close()


def test_episode_dedupe(tmp_path):
    db = DB(tmp_path / "arr.db")
    assert db.episode_state(1, 1, 1) is None
    db.set_episode_state(1, 1, 1, "imported", infohash="h", path="/x")
    assert db.episode_state(1, 1, 1) == "imported"
    db.set_episode_state(1, 1, 1, "downloading")
    assert db.episode_state(1, 1, 1) == "downloading"
    db.close()


def test_monitored_series(tmp_path):
    db = DB(tmp_path / "arr.db")
    sid = db.add_monitored(7, "Show", "tt7", "Returning Series", None)
    assert sid >= 1
    db.set_last_checked(sid, time.time())
    rows = db.list_monitored()
    assert rows[0]["title"] == "Show"
    db.remove_monitored(sid)
    assert db.list_monitored() == []
    db.close()


def test_subtitles_table(tmp_path):
    db = DB(tmp_path / "arr.db")
    db.add_subtitle("/m/x.mkv", "en", "missing", "missing")
    rows = db.list_subtitles("/m/x.mkv")
    assert rows[0]["source"] == "missing"
    db.close()
