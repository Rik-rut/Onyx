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


def test_single_file_movie_does_not_import_unrelated_subtitles(tmp_path):
    shared = tmp_path / "downloads" / "movies"
    shared.mkdir(parents=True)
    movie_a = shared / "MovieA.2023.1080p.mp4"
    movie_a.write_bytes(b"\x00" * 1024)
    movie_b = shared / "MovieB.2021.1080p.mp4"
    movie_b.write_bytes(b"\x00" * 1024)
    sub_b = shared / "MovieB.2021.1080p.en.srt"
    sub_b.write_text("Movie B subtitle text")

    lib = tmp_path / "lib"
    final_a = import_movie(movie_a, lib, "Movie A", 2023)
    assert final_a is not None and final_a.exists()
    # Movie A's destination folder must NOT contain Movie B's subtitle
    dest_dir = final_a.parent
    subs_in_dest = list(dest_dir.glob("*.srt"))
    assert subs_in_dest == []


def test_single_file_movie_imports_adjacent_matching_subtitles(tmp_path):
    shared = tmp_path / "downloads" / "movies"
    shared.mkdir(parents=True)
    movie_a = shared / "MovieA.2023.1080p.mp4"
    movie_a.write_bytes(b"\x00" * 1024)
    sub_a = shared / "MovieA.2023.1080p.en.srt"
    sub_a.write_text("Movie A subtitle text")
    sub_b = shared / "MovieB.2021.1080p.en.srt"
    sub_b.write_text("Movie B subtitle text")

    lib = tmp_path / "lib"
    final_a = import_movie(movie_a, lib, "Movie A", 2023)
    assert final_a is not None and final_a.exists()
    dest_dir = final_a.parent
    subs_in_dest = list(dest_dir.glob("*.srt"))
    assert len(subs_in_dest) == 1
    assert subs_in_dest[0].read_text() == "Movie A subtitle text"


def test_inspect_media_streams_and_has_embedded_subtitles(tmp_path, monkeypatch):
    import json
    from unittest.mock import MagicMock

    from arr.importer.layout import has_embedded_subtitles, inspect_media_streams

    media = tmp_path / "movie.mkv"
    media.write_bytes(b"\x00" * 1024)

    fake_streams_json = json.dumps({
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "index": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "tags": {"language": "eng"},
                "disposition": {"default": 1, "forced": 0},
            },
            {
                "index": 2,
                "codec_name": "subrip",
                "codec_type": "subtitle",
                "tags": {"language": "eng", "title": "English SDH"},
                "disposition": {"default": 0, "forced": 0},
            },
        ]
    })

    mock_run = MagicMock(return_value=MagicMock(stdout=fake_streams_json))
    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("arr.importer.layout._find_ffprobe", lambda: "ffprobe")

    streams = inspect_media_streams(media)
    assert len(streams["video"]) == 1
    assert len(streams["audio"]) == 1
    assert len(streams["subtitle"]) == 1
    assert streams["subtitle"][0]["language"] == "eng"
    assert streams["subtitle"][0]["codec_name"] == "subrip"

    assert has_embedded_subtitles(media, "en") is True
    assert has_embedded_subtitles(media, "es") is False


def test_inspect_media_streams_ffprobe_missing(tmp_path, monkeypatch):
    from arr.importer.layout import has_embedded_subtitles, inspect_media_streams

    media = tmp_path / "movie.mkv"
    media.write_bytes(b"\x00" * 1024)

    monkeypatch.setattr("arr.importer.layout._find_ffprobe", lambda: None)
    streams = inspect_media_streams(media)
    assert streams == {"video": [], "audio": [], "subtitle": []}
    assert has_embedded_subtitles(media, "en") is False


def test_delete_path_removes_files_and_trees(tmp_path):
    from arr.importer.layout import delete_path

    movie = tmp_path / "Inception (2010).mkv"
    movie.write_bytes(b"x")
    assert delete_path(movie) is True
    assert not movie.exists()
    # deleting something that does not exist reports nothing removed
    assert delete_path(movie) is False

    raw = tmp_path / "Inception.2010.1080p.BluRay.x264-[YTS.AG]"
    raw.mkdir()
    (raw / "movie.mkv").write_bytes(b"x")
    (raw / "poster.jpg").write_bytes(b"x")
    assert delete_path(raw) is True
    assert not raw.exists()


def test_prune_empty_dirs_stops_at_media_root(tmp_path):
    from arr.importer.layout import prune_boundary, prune_empty_dirs

    downloads = tmp_path / "downloads"
    movies = downloads / "movies"
    movie_dir = movies / "Inception (2010)"
    movie_dir.mkdir(parents=True)
    media = movie_dir / "Inception (2010).mkv"
    media.write_bytes(b"x")

    assert prune_boundary(media, downloads) == movies
    media.unlink()
    assert prune_empty_dirs(movie_dir, movies) == 1
    assert not movie_dir.exists()
    # the media root itself is never pruned
    assert movies.exists()

    # a non-empty directory is left alone
    keep = movies / "Kung Fu Panda 2 (2011)"
    keep.mkdir(parents=True)
    (keep / "Kung Fu Panda 2 (2011).mkv").write_bytes(b"x")
    assert prune_empty_dirs(keep, movies) == 0
    assert keep.exists()


def test_prune_boundary_staging_and_tv_roots(tmp_path):
    from arr.importer.layout import prune_boundary

    downloads = tmp_path / "downloads"
    staging = downloads / ".staging" / "movies" / "Some.Release.2020"
    assert prune_boundary(staging / "file.mkv", downloads) == downloads / ".staging" / "movies"

    season_dir = downloads / "tv-shows" / "Show (2020)" / "Season 01"
    assert prune_boundary(season_dir / "Show - S01E01.mkv", downloads) == (
        downloads / "tv-shows"
    )


def test_parse_raw_release_folder_names():
    from arr.importer.layout import parse_raw_release_name

    assert parse_raw_release_name("Green Book (2018) [BluRay] [1080p] [YTS.AM]") == (
        "Green Book",
        2018,
    )
    assert parse_raw_release_name(
        "Kung Fu Panda 4 (2024) [1080p] [WEBRip] [x265] [10bit] [5.1] [YTS.MX]"
    ) == ("Kung Fu Panda 4", 2024)
    title, year = parse_raw_release_name(
        "The Apothecary Diaries S02 1080p Dual Audio WEBRip DD+ x265-EMBER"
    )
    assert title == "The Apothecary Diaries"
    assert year is None
    # already-clean folder names are not raw releases
    from arr.importer.layout import looks_like_raw_release

    assert looks_like_raw_release("Green Book (2018)") is False
    assert looks_like_raw_release("Green Book (2018) [BluRay] [1080p] [YTS.AM]") is True
    assert looks_like_raw_release(
        "The Apothecary Diaries S02 1080p Dual Audio WEBRip DD+ x265-EMBER"
    ) is True


def test_cleanup_duplicate_folders_deletes_raw_movie_folder(tmp_path):
    """R2.3: the clean movie folder wins and its raw release twin is removed."""
    from arr.importer.layout import cleanup_duplicate_folders

    movies = tmp_path / "downloads" / "movies"
    clean = movies / "Green Book (2018)"
    clean.mkdir(parents=True)
    (clean / "Green Book (2018).mp4").write_bytes(b"\x00" * 1024)

    raw = movies / "Green Book (2018) [BluRay] [1080p] [YTS.AM]"
    raw.mkdir()
    (raw / "Green.Book.2018.1080p.BluRay.x264-[YTS.AM].mp4").write_bytes(b"\x00" * 1024)
    (raw / "www.YTS.AM.jpg").write_bytes(b"junk")
    (raw / "YIFYStatus.com.txt").write_text("junk")

    removed = cleanup_duplicate_folders(tmp_path / "downloads")

    assert removed == 1
    assert not raw.exists()
    assert [p.name for p in movies.iterdir()] == ["Green Book (2018)"]
    assert (clean / "Green Book (2018).mp4").exists()


def test_cleanup_duplicate_folders_keeps_subtitles_from_raw(tmp_path):
    """Subtitles that only exist in the raw folder are preserved in the clean folder."""
    from arr.importer.layout import cleanup_duplicate_folders

    movies = tmp_path / "downloads" / "movies"
    clean = movies / "Kung Fu Panda 2 (2011)"
    clean.mkdir(parents=True)
    (clean / "Kung Fu Panda 2 (2011).mp4").write_bytes(b"\x00" * 1024)

    raw = movies / "Kung Fu Panda 2 (2011) [1080p] [YTS.AG]"
    raw.mkdir()
    (raw / "Kung.Fu.Panda.2.2011.1080p.BluRay.x264-[YTS.AG].mp4").write_bytes(b"\x00" * 1024)
    (raw / "Kung.Fu.Panda.2.2011.1080p.BluRay.x264-[YTS.AG].en.srt").write_text("subs")

    removed = cleanup_duplicate_folders(tmp_path / "downloads")

    assert removed == 1
    assert not raw.exists()
    srt = clean / "Kung Fu Panda 2 (2011).en.srt"
    assert srt.exists() and srt.read_text() == "subs"


def test_cleanup_duplicate_folders_imports_raw_movie_without_clean_folder(tmp_path):
    """A raw release with no clean counterpart is folded into a single clean folder."""
    from arr.importer.layout import cleanup_duplicate_folders

    movies = tmp_path / "downloads" / "movies"
    raw = movies / "Inception.2010.1080p.BluRay.x264-[YTS.AG]"
    raw.mkdir(parents=True)
    (raw / "Inception.2010.1080p.BluRay.x264-[YTS.AG].mp4").write_bytes(b"\x00" * 1024)
    (raw / "Inception.2010.1080p.BluRay.x264-[YTS.AG].en.srt").write_text("subs")
    (raw / "www.YTS.AG.jpg").write_bytes(b"junk")

    removed = cleanup_duplicate_folders(tmp_path / "downloads")

    assert removed == 1
    assert not raw.exists()
    clean = movies / "Inception (2010)"
    assert (clean / "Inception (2010).mp4").exists()
    assert (clean / "Inception (2010).en.srt").exists()
    assert [p.name for p in clean.iterdir()] == ["Inception (2010).en.srt", "Inception (2010).mp4"]


def test_cleanup_duplicate_folders_tv_moves_missing_episodes(tmp_path):
    """R2.3: TV episode files missing from the clean show folder are imported first."""
    from arr.importer.layout import cleanup_duplicate_folders

    tv = tmp_path / "downloads" / "tv-shows"
    season = tv / "The Apothecary Diaries (2025)" / "Season 02"
    season.mkdir(parents=True)
    (season / "The Apothecary Diaries - S02E01.mkv").write_bytes(b"a" * 256)

    raw = tv / "The Apothecary Diaries S02 1080p Dual Audio WEBRip DD+ x265-EMBER"
    raw.mkdir()
    (raw / "S02E01-Maomao and Maomao [F878C427].mkv").write_bytes(b"a" * 256)
    (raw / "S02E02-Caravan [9141124E].mkv").write_bytes(b"b" * 256)
    (raw / "readme.txt").write_text("junk")

    removed = cleanup_duplicate_folders(tmp_path / "downloads")

    assert removed == 1
    assert not raw.exists()
    names = sorted(p.name for p in season.iterdir())
    assert names == [
        "The Apothecary Diaries - S02E01.mkv",
        "The Apothecary Diaries - S02E02.mkv",
    ]
    assert [p.name for p in tv.iterdir()] == ["The Apothecary Diaries (2025)"]


def test_cleanup_duplicate_folders_leaves_single_folders_alone(tmp_path):
    """Folders with no duplicate pair and non-release folders are untouched."""
    from arr.importer.layout import cleanup_duplicate_folders

    movies = tmp_path / "downloads" / "movies"
    lone = movies / "Lone Movie (2019)"
    lone.mkdir(parents=True)
    (lone / "Lone Movie (2019).mkv").write_bytes(b"\x00" * 512)
    extras = movies / "Trailers and Extras"
    extras.mkdir()
    (extras / "clip.mkv").write_bytes(b"\x00" * 512)

    removed = cleanup_duplicate_folders(tmp_path / "downloads")

    assert removed == 0
    assert lone.exists() and extras.exists()

