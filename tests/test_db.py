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
