from pathlib import Path

from arr.core.models import Series
from arr.importer.layout import (
    episode_dest,
    import_episode,
    import_movie,
    media_files,
    movie_dest,
)


def test_movie_dest():
    p = movie_dest(Path("downloads"), "Inception", 2010, ".mkv")
    assert p == Path("downloads/movies/Inception (2010)/Inception (2010).mkv")


def test_episode_dest():
    p = episode_dest(
        Path("downloads"), "Breaking Bad", 2008, 1, 2, "Cat's in the Bag...", ".mkv"
    )
    expected = (
        "downloads/tv-shows/Breaking Bad (2008)/Season 01/"
        "Breaking Bad - S01E02 - Cat's in the Bag....mkv"
    )
    assert p == Path(expected)


def test_junk_filtered(tmp_path):
    (tmp_path / "Sample").mkdir()
    (tmp_path / "Sample" / "x.mkv").write_bytes(b"x")
    (tmp_path / "movie.mkv").write_bytes(b"x")
    (tmp_path / "info.nfo").write_text("n")
    assert [p.name for p in media_files(tmp_path)] == ["movie.mkv"]


def test_import_movie_hardlink_with_subtitle(tmp_path):
    payload = tmp_path / "pkg"
    payload.mkdir()
    media = payload / "Inception.2010.mkv"
    media.write_bytes(b"\x00" * 1024)
    sub = payload / "Inception.2010.eng.srt"
    sub.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    lib = tmp_path / "lib"
    final = import_movie(payload, lib, "Inception", 2010)
    assert final is not None and final.exists()
    srt = final.parent / "Inception (2010).en.srt"
    assert srt.exists()


def test_import_idempotent_and_collision(tmp_path):
    payload = tmp_path / "pkg2"
    payload.mkdir()
    media = payload / "m.mkv"
    media.write_bytes(b"\x01" * 512)
    lib = tmp_path / "lib"
    a = import_movie(payload, lib, "M", 2020)
    b = import_movie(payload, lib, "M", 2020)
    assert a == b  # same content -> same destination, no duplicate


def test_episode_import_distribution(tmp_path):
    payload = tmp_path / "season1"
    payload.mkdir()
    (payload / "Show.S01E01.mkv").write_bytes(b"a" * 256)
    (payload / "Show.S01E02.mkv").write_bytes(b"b" * 256)
    series = Series(tmdb_id=1, title="Show", year=2020)
    lib = tmp_path / "lib"
    for ep, name in ((1, "Show.S01E01.mkv"), (2, "Show.S01E02.mkv")):
        f = import_episode(payload / name, lib, series, 1, ep, f"Ep{ep}")
        assert f is not None and f.exists()
        assert f.parent.name == "Season 01"
