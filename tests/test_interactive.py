from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console
from typer.testing import CliRunner

from arr.cli import app
from arr.config.settings import DEFAULTS, Config
from arr.core.models import MediaType, Query, Release, Season, Series
from arr.core.parsing import Scored
from arr.interactive.app import run_interactive
from arr.interactive.config_view import interactive_config
from arr.interactive.daemon_view import interactive_daemon
from arr.interactive.movie import interactive_movie
from arr.interactive.queue import interactive_queue
from arr.interactive.series import interactive_series
from arr.interactive.tv import interactive_tv
from arr.interactive.ui import (
    format_eta,
    format_size,
    format_speed,
    live_monitor_downloads,
    make_progress_bar,
    parse_episode_selection,
    print_banner,
    print_header,
    prompt_choice,
    prompt_confirm,
    prompt_text,
    render_episodes_table,
    render_matches_table,
    render_queue_table,
    render_releases_table,
    render_seasons_table,
    render_series_table,
)


@pytest.fixture
def test_cfg(tmp_path):
    values = dict(
        DEFAULTS,
        download_root=str(tmp_path / "downloads"),
        library_root=str(tmp_path / "downloads"),
        import_mode="copy",
    )
    return Config(values=values)


@pytest.fixture
def mock_console():
    return Console(record=True, width=120)


def sample_release(idx: int = 0) -> Release:
    return Release(
        indexer="yts",
        title=f"Sample Movie {idx} (2024) 1080p BluRay x264",
        infohash=f"hash{idx:02d}".ljust(40, "0"),
        magnet=f"magnet:?xt=urn:btih:hash{idx:02d}",
        media_type=MediaType.MOVIE,
        seeds=150,
        peers=20,
        size_bytes=2_500_000_000,
        resolution="1080p",
        source="BluRay",
        codec="x264",
    )


def sample_series() -> Series:
    return Series(
        tmdb_id=123,
        title="Breaking Code",
        year=2022,
        imdb_id="tt9999999",
        status="Returning Series",
        seasons=[
            Season(season_number=1, episodes=[]),
            Season(season_number=2, episodes=[]),
        ],
    )


# =====================================================================
# UI Formatting & Rendering Tests
# =====================================================================
def test_format_helpers():
    assert format_size(None) == "--"
    assert format_size(-10) == "--"
    assert format_size(500) == "500 B"
    assert format_size(2048) == "2 KB"
    assert format_size(10 * 1024 * 1024) == "10.0 MB"
    assert format_size(2.5 * 1024 * 1024 * 1024) == "2.5 GB"

    assert format_speed(None) == "0 B/s"
    assert format_speed(0) == "0 B/s"
    assert format_speed(1024 * 1024 * 2.5) == "2.5 MB/s"

    assert format_eta(None) == "--"
    assert format_eta(-1) == "--"
    assert format_eta(45) == "45s"
    assert format_eta(150) == "2m 30s"
    assert format_eta(3720) == "1h 02m"
    assert format_eta(90000) == "1d 1h"

    # Progress bar
    assert make_progress_bar(0.0) == "[░░░░░░░░░░] 0.0%"
    assert make_progress_bar(78.4) == "[████████░░] 78.4%"
    assert make_progress_bar(100.0) == "[██████████] 100.0%"


def test_parse_episode_selection():
    assert parse_episode_selection("1") == [1]
    assert parse_episode_selection(" 04 ") == [4]
    assert parse_episode_selection("1, 3, 5") == [1, 3, 5]
    assert parse_episode_selection("1-4") == [1, 2, 3, 4]
    assert parse_episode_selection("1-3, 5, 8-10") == [1, 2, 3, 5, 8, 9, 10]
    assert parse_episode_selection("all", max_ep=5) == [1, 2, 3, 4, 5]

    with pytest.raises(ValueError, match="empty"):
        parse_episode_selection("")

    with pytest.raises(ValueError, match="greater than 0"):
        parse_episode_selection("0")

    with pytest.raises(ValueError, match="Invalid"):
        parse_episode_selection("abc")

    with pytest.raises(ValueError, match="cannot exceed"):
        parse_episode_selection("5-2")

    with pytest.raises(ValueError, match="exceeds maximum"):
        parse_episode_selection("15", max_ep=10)


def test_render_new_tables(mock_console):
    # Matches table
    matches = [
        {"id": 1, "name": "Show A", "year": 2021, "status": "Ended", "network": "HBO"},
        {
            "id": 2,
            "name": "Show B",
            "year": 2022,
            "status": "Running",
            "genres": ["Action", "Sci-Fi"],
        },
    ]
    t1 = render_matches_table(matches, "TV Show", mock_console)
    mock_console.print(t1)
    out1 = mock_console.export_text()
    assert "Show A" in out1
    assert "HBO" in out1
    assert "Show B" in out1

    # Seasons table
    mock_console._record_buffer.clear()
    seasons = [
        {
            "season_number": 1,
            "status": "Completed",
            "episode_count": 10,
            "premiere_date": "2021-01-01",
            "end_date": "2021-03-01",
        },
        {
            "season_number": 2,
            "status": "Ongoing",
            "episode_count": 8,
            "premiere_date": "2023-01-01",
            "end_date": None,
        },
    ]
    t2 = render_seasons_table(seasons, mock_console)
    mock_console.print(t2)
    out2 = mock_console.export_text()
    assert "Season 01" in out2
    assert "Completed" in out2
    assert "Ongoing" in out2

    # Episodes table
    mock_console._record_buffer.clear()
    episodes = [
        {"episode_number": 1, "name": "Pilot", "air_date": "2021-01-01"},
        {"episode_number": 2, "name": "Second", "air_date": "2021-01-08"},
    ]
    t3 = render_episodes_table(episodes, mock_console)
    mock_console.print(t3)
    out3 = mock_console.export_text()
    assert "E01" in out3
    assert "Pilot" in out3


def test_render_tables(mock_console):
    # Release table
    releases = [sample_release(0), sample_release(1)]
    table = render_releases_table(releases, mock_console)
    assert table is not None
    mock_console.print(table)
    out = mock_console.export_text()
    assert "Sample Movie 0" in out
    assert "1080p" in out

    # Queue table
    items = [
        {
            "infohash": "abcdef123456",
            "title": "Show S01",
            "media_type": "tv",
            "state": "downloading",
        },
        {
            "infohash": "112233445566",
            "title": "Movie X",
            "media_type": "movie",
            "state": "completed",
        },
        {
            "infohash": "998877665544",
            "title": "Movie Y",
            "media_type": "movie",
            "state": "imported",
        },
        {
            "infohash": "aabbccddeeff",
            "title": "Show S02",
            "media_type": "tv",
            "state": "queued",
        },
    ]
    torrents_by_hash = {
        "abcdef123456": {
            "percentDone": 0.452,
            "rateDownload": 2_000_000,
            "eta": 300,
        }
    }
    q_table = render_queue_table(items, torrents_by_hash, mock_console)
    assert q_table is not None
    mock_console.print(q_table)
    q_out = mock_console.export_text()
    assert "Show S01" in q_out
    assert "45.2%" in q_out

    # Series table
    s_items = [
        {
            "id": 1,
            "title": "Breaking Code",
            "status": "Returning Series",
            "imported_episodes": 10,
            "pending_episodes": 2,
            "missing_episodes": 3,
            "last_checked_at": "2026-10-09",
        }
    ]
    s_table = render_series_table(s_items, mock_console)
    assert s_table is not None
    mock_console.print(s_table)
    s_out = mock_console.export_text()
    assert "Breaking Code" in s_out
    assert "Returning Series" in s_out


def test_banners_and_headers(mock_console):
    print_banner(mock_console)
    print_header("Test Header", "Test Subtitle", mock_console)
    out = mock_console.export_text()
    assert "ARR" in out
    assert "Test Header" in out
    assert "Test Subtitle" in out


# =====================================================================
# Prompt Helper Tests
# =====================================================================
def test_prompt_helpers(mock_console):
    # prompt_text
    with patch.object(mock_console, "input", side_effect=["hello", ""]):
        assert prompt_text("Enter name", c=mock_console) == "hello"
        assert prompt_text("Enter name", default="world", c=mock_console) == "world"

    with patch.object(mock_console, "input", side_effect=["b"]):
        assert prompt_text("Enter name", allow_back=True, c=mock_console) is None

    with patch.object(mock_console, "input", side_effect=KeyboardInterrupt):
        assert prompt_text("Enter name", c=mock_console) is None

    # prompt_choice
    with patch.object(mock_console, "input", side_effect=["invalid", "2"]):
        assert prompt_choice("Pick", ["1", "2", "3"], c=mock_console) == "2"

    with patch.object(mock_console, "input", side_effect=[""]):
        assert prompt_choice("Pick", ["1", "2"], default="1", c=mock_console) == "1"

    # prompt_confirm
    with patch.object(mock_console, "input", side_effect=["y", "n", ""]):
        assert prompt_confirm("Sure?", default=False, c=mock_console) is True
        assert prompt_confirm("Sure?", default=True, c=mock_console) is False
        assert prompt_confirm("Sure?", default=True, c=mock_console) is True


# =====================================================================
# Configuration & Daemon Status Views
# =====================================================================
def test_interactive_config_view(test_cfg, mock_console):
    with patch("arr.interactive.config_view.prompt_text", side_effect=["1", "", "b"]):
        interactive_config(test_cfg, mock_console)
    out = mock_console.export_text()
    assert "Configuration & Settings" in out
    assert "Active Configuration (Redacted)" in out


def test_interactive_daemon_view(test_cfg, mock_console):
    # Test when transmission is offline
    with (
        patch("arr.transmission.process.RpcClient.list_torrents", side_effect=Exception("offline")),
        patch("arr.interactive.daemon_view.find_daemon", return_value=None),
        patch("arr.interactive.daemon_view.port_in_use", return_value=False),
        patch("arr.interactive.daemon_view.prompt_text", side_effect=["b"]),
    ):
        interactive_daemon(test_cfg, mock_console)
    out = mock_console.export_text()
    assert "Transmission Daemon Offline" in out

    # Test when transmission is online
    mock_console._record_buffer.clear()
    with (
        patch("arr.transmission.process.RpcClient.list_torrents", return_value=[{"id": 1}]),
        patch("arr.interactive.daemon_view.find_daemon", return_value="/bin/transmission-daemon"),
        patch("arr.interactive.daemon_view.prompt_text", side_effect=["b"]),
    ):
        interactive_daemon(test_cfg, mock_console)
    out2 = mock_console.export_text()
    assert "Transmission Daemon Online" in out2


# =====================================================================
# Queue Management View
# =====================================================================
def test_interactive_queue_view(test_cfg, mock_console):
    items = [
        {
            "infohash": "hash01",
            "title": "Test Download",
            "media_type": "movie",
            "state": "downloading",
        }
    ]

    with (
        patch("arr.interactive.queue.list_queue", return_value=items),
        patch("arr.transmission.process.RpcClient.list_torrents", return_value=[]),
        patch("arr.interactive.queue.prompt_text", side_effect=["2", "hash01", "", "b"]),
        patch("arr.interactive.queue.prompt_confirm", return_value=False),
        patch("arr.interactive.queue.cancel_download", new_callable=AsyncMock) as mock_cancel,
    ):
        interactive_queue(test_cfg, mock_console)
        mock_cancel.assert_called_once_with("hash01", test_cfg)

    # Test cancel with index "0"
    with (
        patch("arr.interactive.queue.list_queue", return_value=items),
        patch("arr.transmission.process.RpcClient.list_torrents", return_value=[]),
        patch("arr.interactive.queue.prompt_text", side_effect=["2", "0", "", "b"]),
        patch("arr.interactive.queue.prompt_confirm", return_value=False),
        patch("arr.interactive.queue.cancel_download", new_callable=AsyncMock) as mock_cancel,
    ):
        interactive_queue(test_cfg, mock_console)
        mock_cancel.assert_called_once_with("hash01", test_cfg)

    # Test cancel with short prefix "hash0"
    with (
        patch("arr.interactive.queue.list_queue", return_value=items),
        patch("arr.transmission.process.RpcClient.list_torrents", return_value=[]),
        patch("arr.interactive.queue.prompt_text", side_effect=["2", "hash0", "", "b"]),
        patch("arr.interactive.queue.prompt_confirm", return_value=False),
        patch("arr.interactive.queue.cancel_download", new_callable=AsyncMock) as mock_cancel,
    ):
        interactive_queue(test_cfg, mock_console)
        mock_cancel.assert_called_once_with("hash01", test_cfg)

    # Test cancel when not found (SystemExit 3 handled gracefully)
    with (
        patch("arr.interactive.queue.list_queue", return_value=items),
        patch("arr.transmission.process.RpcClient.list_torrents", return_value=[]),
        patch("arr.interactive.queue.prompt_text", side_effect=["2", "unknown", "", "b"]),
        patch("arr.interactive.queue.prompt_confirm", return_value=False),
        patch("arr.interactive.queue.cancel_download", side_effect=SystemExit(3)),
    ):
        mock_console._record_buffer.clear()
        interactive_queue(test_cfg, mock_console)
        out = mock_console.export_text()
        assert "not found" in out.lower()

    # Test manual import
    with (
        patch("arr.interactive.queue.list_queue", return_value=items),
        patch("arr.transmission.process.RpcClient.list_torrents", return_value=[]),
        patch("arr.interactive.queue.prompt_text", side_effect=["3", "hash01", "", "b"]),
        patch("arr.interactive.queue.prompt_confirm", return_value=True),
        patch("arr.interactive.queue.import_download", new_callable=AsyncMock) as mock_import,
    ):
        interactive_queue(test_cfg, mock_console)
        mock_import.assert_called_once_with("hash01", test_cfg, overwrite=True)


# =====================================================================
# Series Monitoring View
# =====================================================================
def test_interactive_series_view(test_cfg, mock_console):
    series_list_data = [
        {
            "id": 42,
            "title": "Breaking Code",
            "status": "Ended",
            "imported_episodes": 5,
            "pending_episodes": 0,
            "missing_episodes": 0,
            "last_checked_at": None,
        }
    ]

    # Test add series
    with (
        patch("arr.interactive.series.series_list", return_value=series_list_data),
        patch("arr.interactive.series.prompt_text", side_effect=["1", "Breaking Code", "", "b"]),
        patch("arr.interactive.series.series_add", new_callable=AsyncMock) as mock_add,
    ):
        interactive_series(test_cfg, mock_console)
        mock_add.assert_called_once_with("Breaking Code", test_cfg)

    # Test force check series
    with (
        patch("arr.interactive.series.series_list", return_value=series_list_data),
        patch("arr.interactive.series.prompt_text", side_effect=["2", "42", "", "b"]),
        patch("arr.interactive.series.series_check", new_callable=AsyncMock) as mock_check,
    ):
        interactive_series(test_cfg, mock_console)
        mock_check.assert_called_once_with(42, test_cfg)

    # Test remove series
    with (
        patch("arr.interactive.series.series_list", return_value=series_list_data),
        patch("arr.interactive.series.prompt_text", side_effect=["3", "42", "", "b"]),
        patch("arr.interactive.series.prompt_confirm", return_value=False),
        patch("arr.interactive.series.series_remove") as mock_remove,
    ):
        interactive_series(test_cfg, mock_console)
        mock_remove.assert_called_once_with(42, test_cfg, delete_files=False)


# =====================================================================
# Movie Search & Download Flow
# =====================================================================
def test_interactive_movie_flow(test_cfg, mock_console):
    rel = sample_release(0)
    score_dict = {
        "seeders": 150,
        "resolution_rank": 1,
        "source_rank": 1,
        "codec_rank": 1,
        "size_bytes": 2500000000,
        "infohash": rel.infohash,
    }
    scored = Scored(release=rel, score=score_dict)
    q = Query(
        media_type=MediaType.MOVIE,
        text="Inception",
        title="Inception",
        year=2010,
        imdb_id="tt1375666",
    )

    # Flow with explain, auto, and confirm
    imdb_meta = {"title": "Inception", "year": 2010, "imdb_id": "tt1375666"}
    with (
        patch("arr.metadata.imdb.ImdbClient.search_movie", return_value=imdb_meta),
        patch(
            "arr.interactive.movie.search_candidates",
            new_callable=AsyncMock,
            return_value=([rel], [scored], q),
        ),
        patch("arr.interactive.movie.prompt_text", side_effect=["Inception", "explain", "0", ""]),
        patch("arr.interactive.movie.prompt_confirm", return_value=True),
        patch(
            "arr.interactive.movie.enqueue_release",
            new_callable=AsyncMock,
            return_value=(True, "Started downloading"),
        ) as mock_enqueue,
    ):
        interactive_movie(test_cfg, mock_console)
        mock_enqueue.assert_called_once()
        out = mock_console.export_text()
        assert "Inception" in out
        assert "Full Candidate Score Breakdown" in out
        assert "Started downloading" in out


# =====================================================================
# TV Search & Download Flow
# =====================================================================
def test_interactive_tv_flow_entire_series(test_cfg, mock_console):
    s = sample_series()
    with (
        patch("arr.metadata.tvmaze.TvmazeClient.search_tv", return_value={"id": 123}),
        patch("arr.metadata.tvmaze.TvmazeClient.full_series", return_value=s),
        patch("arr.interactive.tv.prompt_text", side_effect=["Breaking Code", "1", ""]),
        patch("arr.interactive.tv.prompt_confirm", return_value=True),
        patch("arr.pipeline.download_tv", new_callable=AsyncMock) as mock_dt,
    ):
        interactive_tv(test_cfg, mock_console)
        mock_dt.assert_called_once()
        out = mock_console.export_text()
        assert "Entire series enqueued" in out


def test_interactive_tv_flow_specific_season(test_cfg, mock_console):
    s = sample_series()
    rel = sample_release(1)
    rel.media_type = MediaType.TV
    score_dict = {
        "seeders": 150,
        "resolution_rank": 1,
        "source_rank": 1,
        "codec_rank": 1,
        "size_bytes": 2500000000,
        "infohash": rel.infohash,
    }
    scored = Scored(release=rel, score=score_dict)
    q = Query(media_type=MediaType.TV, text="Breaking Code", season=1)

    with (
        patch("arr.metadata.tvmaze.TvmazeClient.search_tv", return_value={"id": 123}),
        patch("arr.metadata.tvmaze.TvmazeClient.full_series", return_value=s),
        patch(
            "arr.interactive.tv.prompt_text",
            side_effect=["Breaking Code", "2", "1", "auto", ""],
        ),
        patch(
            "arr.interactive.tv.search_candidates",
            new_callable=AsyncMock,
            return_value=([rel], [scored], q),
        ),
        patch("arr.interactive.tv.prompt_confirm", return_value=True),
        patch(
            "arr.interactive.tv.enqueue_release",
            new_callable=AsyncMock,
            return_value=(True, "Started downloading"),
        ) as mock_enq,
    ):
        interactive_tv(test_cfg, mock_console)
        mock_enq.assert_called_once()
        out = mock_console.export_text()
        assert "Started downloading" in out


# =====================================================================
# Main Application Loop & Ctrl+C Handling
# =====================================================================
def test_main_menu_exit(test_cfg, mock_console):
    with patch("arr.interactive.app.prompt_text", side_effect=["0"]):
        ret = run_interactive(test_cfg, mock_console)
        assert ret == 0
        assert "Goodbye" in mock_console.export_text()


def test_main_menu_keyboard_interrupt(test_cfg, mock_console):
    with patch("arr.interactive.app.prompt_text", side_effect=KeyboardInterrupt):
        ret = run_interactive(test_cfg, mock_console)
        assert ret == 0
        assert "Exiting ARR interactive mode" in mock_console.export_text()


def test_main_menu_invalid_then_exit(test_cfg, mock_console):
    with patch("arr.interactive.app.prompt_text", side_effect=["99", "q"]):
        ret = run_interactive(test_cfg, mock_console)
        assert ret == 0
        out = mock_console.export_text()
        assert "Invalid selection '99'" in out
        assert "Goodbye" in out


# =====================================================================
# Standalone CLI Command Test
# =====================================================================
def test_cli_interactive_command():
    runner = CliRunner()
    with patch("arr.interactive.run_interactive", return_value=0) as mock_interactive:
        result = runner.invoke(app, ["interactive"])
        assert result.exit_code == 0
        mock_interactive.assert_called_once()


# =====================================================================
# R15 Enhanced Interactive Flow Tests
# =====================================================================
def test_interactive_tv_flow_multi_match_selection(test_cfg, mock_console):
    s = sample_series()
    matches = [
        {"id": 101, "name": "Other Show", "year": 2010, "status": "Ended"},
        {"id": 123, "name": "Breaking Code", "year": 2022, "status": "Returning Series"},
    ]
    with (
        patch("arr.metadata.tvmaze.TvmazeClient.search_tv_shows", return_value=matches),
        patch("arr.metadata.tvmaze.TvmazeClient.full_series", return_value=s),
        patch("arr.metadata.tvmaze.TvmazeClient.seasons_overview", return_value=[]),
        patch("arr.interactive.tv.prompt_text", side_effect=["Breaking", "1", "1", ""]),
        patch("arr.interactive.tv.prompt_confirm", return_value=True),
        patch("arr.pipeline.download_tv", new_callable=AsyncMock) as mock_dt,
    ):
        interactive_tv(test_cfg, mock_console)
        mock_dt.assert_called_once()
        out = mock_console.export_text()
        assert "Breaking Code" in out
        assert "Entire series enqueued" in out


def test_interactive_tv_flow_multi_episode_selection(test_cfg, mock_console):
    from arr.core.models import Episode

    s = sample_series()
    s.seasons[0].episodes = [
        Episode(tmdb_id=123, season_number=1, episode_number=1, name="Pilot"),
        Episode(tmdb_id=123, season_number=1, episode_number=2, name="Second"),
    ]
    rel1 = sample_release(1)
    rel1.media_type = MediaType.TV
    scored1 = Scored(release=rel1, score={"seeders": 100})
    q1 = Query(media_type=MediaType.TV, text="Breaking Code", season=1, episode=1)

    with (
        patch(
            "arr.metadata.tvmaze.TvmazeClient.search_tv_shows",
            return_value=[{"id": 123, "name": "Breaking Code"}],
        ),
        patch("arr.metadata.tvmaze.TvmazeClient.full_series", return_value=s),
        patch("arr.metadata.tvmaze.TvmazeClient.seasons_overview", return_value=[]),
        patch(
            "arr.interactive.tv.prompt_text",
            side_effect=["Breaking Code", "2", "1", "2", "1-2", ""],
        ),
        patch(
            "arr.interactive.tv.search_candidates",
            new_callable=AsyncMock,
            return_value=([rel1], [scored1], q1),
        ),
        patch("arr.interactive.tv.prompt_confirm", return_value=True),
        patch(
            "arr.interactive.tv.enqueue_release",
            new_callable=AsyncMock,
            return_value=(True, "Started downloading"),
        ) as mock_enq,
    ):
        interactive_tv(test_cfg, mock_console)
        assert mock_enq.call_count == 2
        out = mock_console.export_text()
        assert "Enqueued 2/2 episodes" in out


def test_interactive_movie_flow_multi_match_selection(test_cfg, mock_console):
    rel = sample_release(0)
    score_dict = {"seeders": 150}
    scored = Scored(release=rel, score=score_dict)
    q = Query(media_type=MediaType.MOVIE, text="Batman", title="Batman Begins", year=2005)

    matches = [
        {"id": "tt0096895", "title": "Batman", "year": 1989, "imdb_id": "tt0096895"},
        {"id": "tt0372784", "title": "Batman Begins", "year": 2005, "imdb_id": "tt0372784"},
    ]
    with (
        patch("arr.metadata.imdb.ImdbClient.search_movies", return_value=matches),
        patch(
            "arr.interactive.movie.search_candidates",
            new_callable=AsyncMock,
            return_value=([rel], [scored], q),
        ) as mock_cand,
        patch("arr.interactive.movie.prompt_text", side_effect=["Batman", "1", "auto", ""]),
        patch("arr.interactive.movie.prompt_confirm", return_value=True),
        patch(
            "arr.interactive.movie.enqueue_release",
            new_callable=AsyncMock,
            return_value=(True, "Started downloading"),
        ) as mock_enqueue,
    ):
        interactive_movie(test_cfg, mock_console)
        mock_cand.assert_called_once_with(
            MediaType.MOVIE,
            "Batman Begins",
            test_cfg,
            year=2005,
            imdb_id="tt0372784",
            title="Batman Begins",
        )
        mock_enqueue.assert_called_once()
        out = mock_console.export_text()
        assert "Batman Begins" in out


def test_interactive_queue_live_monitor(test_cfg, mock_console):
    with (
        patch("arr.interactive.queue.list_queue", return_value=[]),
        patch("arr.interactive.queue.prompt_text", side_effect=["4", "b"]),
        patch("arr.interactive.queue.live_monitor_downloads") as mock_live,
    ):
        interactive_queue(test_cfg, mock_console)
        mock_live.assert_called_once()


def test_live_monitor_downloads_safe_exit(test_cfg, mock_console):
    with patch("arr.transmission.process.RpcClient.list_torrents", return_value=[]):
        live_monitor_downloads(test_cfg, mock_console, max_iterations=1, poll_interval=0.01)
    out = mock_console.export_text()
    assert "Live Download Monitor" in out


def test_check_exit_keypress():
    import sys
    from unittest.mock import MagicMock

    from arr.interactive.ui import check_exit_keypress

    # Test Windows path
    mock_msvcrt_hit = MagicMock(
        kbhit=MagicMock(return_value=True),
        getch=MagicMock(return_value=b"q"),
    )
    with patch.object(sys, "platform", "win32"):
        with patch.dict("sys.modules", {"msvcrt": mock_msvcrt_hit}):
            assert check_exit_keypress() is True
        with patch.dict("sys.modules", {"msvcrt": MagicMock(kbhit=MagicMock(return_value=False))}):
            assert check_exit_keypress() is False

    # Test POSIX path
    with patch.object(sys, "platform", "linux"):
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("sys.stdin.read", return_value="q"),
            patch("select.select", return_value=([MagicMock()], [], [])),
        ):
            assert check_exit_keypress() is True
        with (
            patch("sys.stdin.isatty", return_value=True),
            patch("select.select", return_value=([], [], [])),
        ):
            assert check_exit_keypress() is False


def test_interactive_queue_pause_and_resume(test_cfg, mock_console):
    with (
        patch(
            "arr.interactive.queue.list_queue",
            return_value=[{"infohash": "h123", "title": "Test Item"}],
        ),
        patch("arr.interactive.queue.prompt_text", side_effect=["5", "0", "", "6", "0", "", "b"]),
        patch("arr.interactive.queue.pause_download") as mock_pause,
        patch("arr.interactive.queue.resume_download") as mock_resume,
    ):
        interactive_queue(test_cfg, mock_console)
        mock_pause.assert_called_once_with("h123", test_cfg)
        mock_resume.assert_called_once_with("h123", test_cfg)


def test_interactive_main_menu_direct_magnet(test_cfg, mock_console):
    from arr.interactive.app import run_interactive

    with (
        patch("arr.transmission.process.ensure_daemon"),
        patch("arr.transmission.process.port_in_use", return_value=True),
        patch(
            "arr.interactive.app.prompt_text",
            side_effect=["d", "magnet:?xt=urn:btih:xyz", "", "0"],
        ),
        patch("arr.pipeline.download_magnet") as mock_dl_mag,
    ):
        code = run_interactive(test_cfg, mock_console)
        assert code == 0
        mock_dl_mag.assert_called_once_with("magnet:?xt=urn:btih:xyz", test_cfg)


def test_interactive_config_edit(test_cfg, mock_console, tmp_path):
    from arr.interactive.config_view import interactive_config

    custom_cfg_path = tmp_path / "config.toml"
    with (
        patch("arr.config.settings.default_config_path", return_value=custom_cfg_path),
        patch(
            "arr.interactive.config_view.prompt_text",
            side_effect=[
                "2",
                "1",
                "/custom/downloads",
                "",
                "2",
                "3",
                "2",
                "",
                "b",
            ],
        ),
    ):
        interactive_config(test_cfg, mock_console)
        assert test_cfg.get("download_root") == "/custom/downloads"
        assert test_cfg.get("import_mode") == "copy"
        assert custom_cfg_path.exists()


def test_interactive_library_browser(test_cfg, mock_console, tmp_path):
    from arr.interactive.library_view import (
        get_library_movies,
        get_library_shows,
        interactive_library,
    )

    movies_dir = tmp_path / "downloads" / "movies"
    m_folder = movies_dir / "Inception (2010)"
    m_folder.mkdir(parents=True)
    (m_folder / "Inception (2010).mkv").write_bytes(b"\x00" * 1024)

    tv_dir = tmp_path / "downloads" / "tv-shows"
    show_folder = tv_dir / "Breaking Bad (2008)" / "Season 01"
    show_folder.mkdir(parents=True)
    (show_folder / "Breaking Bad - S01E01 - Pilot.mkv").write_bytes(b"\x00" * 1024)

    test_cfg.values["library_root"] = str(tmp_path / "downloads")

    movies = get_library_movies(movies_dir)
    assert len(movies) == 1
    assert "Inception" in movies[0]["title"]
    assert movies[0]["primary_ext"] == ".mkv"

    shows = get_library_shows(tv_dir, test_cfg)
    assert len(shows) == 1
    assert "Breaking Bad" in shows[0]["title"]
    assert shows[0]["episodes_count"] == 1

    with patch(
        "arr.interactive.library_view.prompt_text",
        side_effect=["1", "b", "2", "b", "b"],
    ):
        interactive_library(test_cfg, mock_console)


def test_library_hides_raw_torrent_duplicates(test_cfg, tmp_path):
    from arr.interactive.library_view import get_library_movies
    from arr.pipeline import _db

    test_cfg.values["db_path"] = str(tmp_path / "arr.db")
    movies_dir = tmp_path / "downloads" / "movies"

    clean = movies_dir / "Inception (2010)"
    clean.mkdir(parents=True)
    (clean / "Inception (2010).mkv").write_bytes(b"\x00" * 1024)

    raw = movies_dir / "Inception.2010.1080p.BluRay.x264-YTS.AG"
    raw.mkdir(parents=True)
    (raw / "Inception.2010.1080p.BluRay.x264-YTS.AG.mkv").write_bytes(b"\x00" * 1024)

    orphan = movies_dir / "Orphan Movie (2019)"
    orphan.mkdir(parents=True)
    (orphan / "Orphan Movie (2019).mkv").write_bytes(b"\x00" * 1024)

    db = _db(test_cfg)
    db.add_download("a" * 40, media_type="movie", title="Inception")
    db.set_download_state(
        "a" * 40,
        "imported",
        content_path=str(raw),
        destination_path=str(clean / "Inception (2010).mkv"),
    )
    db.add_download("b" * 40, media_type="movie", title="Orphan Movie")
    db.set_download_state("b" * 40, "skipped", content_path=str(orphan))
    db.close()

    titles = [m["title"] for m in get_library_movies(movies_dir, test_cfg)]
    assert "Inception (2010)" in titles
    assert raw.name not in titles  # raw duplicate hidden
    assert "Orphan Movie (2019)" in titles  # no imported copy -> kept


def test_movie_filter_and_sort(test_cfg, mock_console):
    from arr.core.models import MediaType, Release
    from arr.interactive.movie import interactive_movie

    r1 = Release(
        title="Inception.2010.720p.BluRay",
        infohash="hash1",
        size_bytes=1000,
        seeds=10,
        indexer="yts",
        magnet="magnet:?xt=urn:btih:hash1",
        media_type=MediaType.MOVIE,
    )
    r2 = Release(
        title="Inception.2010.1080p.BluRay",
        infohash="hash2",
        size_bytes=2000,
        seeds=50,
        indexer="yts",
        magnet="magnet:?xt=urn:btih:hash2",
        media_type=MediaType.MOVIE,
    )

    with (
        patch("arr.metadata.imdb.ImdbClient.search_movies", return_value=[]),
        patch("arr.metadata.imdb.ImdbClient.search_movie", return_value=None),
        patch(
            "arr.pipeline.search_candidates",
            return_value=([r1, r2], [], None),
        ),
        patch(
            "arr.interactive.movie.prompt_text",
            side_effect=[
                "Inception",
                "f 1080p",
                "sort seeds",
                "b",
            ],
        ),
    ):
        interactive_movie(test_cfg, mock_console)


def test_app_exit_daemon_cleanup(test_cfg, mock_console):
    from arr.interactive.app import run_interactive

    mock_daemon = MagicMock()
    with (
        patch("arr.transmission.process.port_in_use", return_value=False),
        patch("arr.transmission.process.ensure_daemon", return_value=mock_daemon),
        patch("arr.interactive.app.prompt_text", return_value="0"),
        patch("arr.interactive.app.prompt_confirm", return_value=False),
    ):
        code = run_interactive(test_cfg, mock_console)
        assert code == 0
        mock_daemon.stop.assert_called_once()


def test_daemon_view_open_web(test_cfg, mock_console):
    from arr.interactive.daemon_view import interactive_daemon

    with (
        patch("arr.transmission.process.RpcClient.list_torrents", return_value=[]),
        patch("arr.transmission.process.port_in_use", return_value=True),
        patch("arr.interactive.daemon_view.prompt_text", side_effect=["w", "", "b"]),
        patch("webbrowser.open") as mock_web_open,
    ):
        interactive_daemon(test_cfg, mock_console)
        mock_web_open.assert_called_once_with("http://127.0.0.1:9091/transmission/web/")




