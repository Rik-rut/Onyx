# arr

CLI client that searches public torrent indexers (YTS for movies, EZTV for TV, Nyaa for anime),
ranks releases by seeders/quality, hands the chosen magnet to a locally managed
`transmission-daemon`, and imports completed downloads into a Sonarr/Radarr-compatible library.
No GUI/TUI. See `LEGAL.md` for the legal posture and `GOTCHAS.md` for known failure modes.

## Requirements

- [uv](https://docs.astral.sh/uv/) (manages Python + deps; no `pip`/`venv` commands)
- `transmission-daemon` + `transmission-remote` on PATH (Windows probe also checks `%ProgramFiles%\Transmission`)
- Optional: `ffmpeg` (`.ass`/`.sub` → `.srt` conversion), OpenSubtitles API key

## Install / run

Windows:

```bat
run.bat                :: first run: uv sync, then `arr --help`
run.bat search movie "Inception"
run.bat download movie "Inception" --auto
```

Linux/macOS:

```sh
chmod +x run.sh
./run.sh --help
```

Development:

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy arr
```

## Config

`arr config init` writes a documented template. Default paths:
`%APPDATA%\arr\config.toml` (Windows), `$XDG_CONFIG_HOME/arr/config.toml` or
`~/.config/arr/config.toml` (Linux/macOS). Override with `--config <path>`.

`arr config show` prints effective config with secrets redacted (`--show-secrets` to reveal).

Key settings: `tmdb_api_key`, `opensubtitles_api_key`, `download_root`, `library_root`,
`transmission_rpc_*`, `yts_base_url`/`eztv_base_url`/`nyaa_base_url`, `seeding_policy`
(`ratio`/`time`/`manual`/`remove_on_import`), `import_mode` (`hardlink`/`copy`/`move`),
`max_concurrent_downloads` (default 3), `prefer_season_packs`, `subtitle_languages` (default `["en"]`),
`subtitles_enabled`, `subtitles_forced_only`, `monitor_poll_interval_minutes`,
`monitor_lookahead_days`, `unmonitor_ended_series`.

## Command reference

```
arr search movie <query> [--json]
arr search tv <query> [-s N] [-e N] [--json]
arr download movie <query> [--pick N | --auto] [--yes] [--no-wait] [--force]
arr download tv <query> [-s N] [-e N] [--pack] [--pick N | --auto] [--yes] [--no-wait] [--force]
arr series add <query>
arr series list [--json]
arr series remove <id> [--delete-files]
arr series check <id>
arr queue [--json]
arr status <id> [--json]
arr cancel <id> [--delete-data]
arr import <id> [--overwrite]
arr daemon
arr config init|show|path
arr version
```

Exit codes: `0` ok, `1` runtime error, `2` usage error/no selection, `3` no results,
`4` dependency unavailable (transmission/TMDB).

### TV scope rules

- `download tv "Show"` → entire series (all seasons/episodes), printed + confirmed unless `--yes`
- `-s N` → one season; `-s N -e M` → one episode; `--pack` → prefer a season pack
- An episode already `imported`/`downloading` is never re-enqueued unless `--force`
- A chosen season pack marks every episode in that season `imported`

### Monitoring

`series add` resolves the show via TMDB, records it in `monitored_series`, and does an initial
whole-series fetch. `arr daemon` runs a tick every `monitor_poll_interval_minutes`: refreshes TMDB
(shorter TTL for `Returning Series` episode lists), selects aired-or-lookahead episodes that are not
already imported/downloading, searches → ranks → enqueues (respecting `max_concurrent_downloads`),
imports completed downloads, applies the seeding policy, then sleeps. Ended/canceled shows keep
showing in `series list`; `unmonitor_ended_series = true` auto-removes them. Indexer failures during a
tick mark affected episodes `retry_pending` and never halt the loop. Ticks are idempotent.

## Library layout

```
downloads/
  movies/<Title> (<Year>)/<Title> (<Year>).<ext>
                                     <Title> (<Year>).en.srt
  tv-shows/<Show> (<Year>)/Season NN/<Show> - S01E01 - <Episode Title>.<ext>
                                                       <...>.en.srt
```

Staging lives in `downloads/movies/.incomplete/` and `downloads/tv-shows/.incomplete/` (never scanned
as library). Names follow Sonarr/Radarr conventions so Plex/Jellyfin identify files and subtitles
without manual matching. Import tries a hardlink first, falls back to copy on `EXDEV`/failure, then to
move only when `import_mode = "move"`. Collisions: identical size+hash → skip; else `.1`/`.2` suffix;
`--overwrite` replaces. Sibling subtitles are renamed to `<basename>.<lang>.<ext>` so the language
track is recognized.

## Seeding policy

`ratio` (stop at `seed_ratio`), `time` (stop after `seed_time_hours`), `manual` (never auto-remove),
`remove_on_import` (remove torrent data right after a successful **copy** import). Hardlink imports
keep the data in place so seeding can continue (the trade-off is printed once per run).
`remove_on_import` + `hardlink` is refused — it would delete the library's only copy.

## Subtitles

Default: every imported movie/episode gets an English subtitle next to the media as
`<basename>.en.srt`. Source priority: sibling subtitles in the torrent → OpenSubtitles official API
(`opensubtitles_api_key`, per-episode `imdb_id`+season+episode or movie `imdb_id`/`tmdb_id`,
`subtitles_forced_only` filters to forced tracks, quota exhaustion → `quota_exceeded` and retry next
tick) → skip with a warning and record `missing`. `subtitles_enabled = false` disables the whole
subsystem. The `subtitles` table records media path, language, source (`sibling`/`embedded`/
`opensubtitles`/`missing`), state, and the OpenSubtitles subtitle id.
