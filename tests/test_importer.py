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
        "Breaking Bad - S01E02 - Cat's in the Bag.mkv"
    )
    assert p == Path(expected)


def test_sanitize_illegal_characters():
    from arr.importer.layout import sanitize_name

    assert sanitize_name("Star Trek: Discovery") == "Star Trek - Discovery"
    assert sanitize_name("What If...?") == "What If"
    assert sanitize_name('Bad/Name\\With*Chars') == "BadNameWithChars"
    assert sanitize_name("  Trailing dots...  ") == "Trailing dots"
    assert sanitize_name("") == "Unknown"
    assert sanitize_name("CON") == "_CON"


def test_movie_dest_sanitizes_title():
    p = movie_dest(Path("downloads"), "Star Trek: The Motion Picture", 1979, ".mkv")
    assert p == Path(
        "downloads/movies/Star Trek - The Motion Picture (1979)/"
        "Star Trek - The Motion Picture (1979).mkv"
    )


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


def test_episode_import_does_not_cross_assign_subtitles(tmp_path):
    """Importing S01E01 must not rename S01E02's subtitle to S01E01's basename."""
    payload = tmp_path / "pack"
    payload.mkdir()
    (payload / "Show.S01E01.mkv").write_bytes(b"a" * 256)
    (payload / "Show.S01E02.mkv").write_bytes(b"b" * 256)
    (payload / "Show.S01E01.en.srt").write_text("ep1 subs")
    (payload / "Show.S01E02.en.srt").write_text("ep2 subs")
    (payload / "release.en.srt").write_text("untagged subs")
    series = Series(tmdb_id=1, title="Show", year=2020)
    lib = tmp_path / "lib"
    f = import_episode(payload / "Show.S01E01.mkv", lib, series, 1, 1, "One")
    assert f is not None
    srt = f.parent / f"{f.stem}.en.srt"
    assert srt.exists()
    assert srt.read_text() == "ep1 subs"
    # no stray subtitle for the other episode was placed
    assert not (f.parent / "Show - S01E02 - .en.srt").exists()
    # only two subtitle files should exist next to media (ep1 + untagged collision),
    # but crucially ep2's subtitle content is not present
    contents = {p.read_text() for p in f.parent.glob("*.srt")}
    assert "ep2 subs" not in contents
