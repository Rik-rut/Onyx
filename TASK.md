# Autonomous Task

## Objective

Build a Python CLI-only application that searches public torrent indexers (YTS for movies, EZTV for TV, Nyaa for anime) for movies and TV episodes, resolves titles via TMDB, ranks releases by seeders and quality, hands the chosen magnet to a locally managed `transmission-daemon`, and imports the completed download into a `downloads/movies` and `downloads/tv-shows` library using Sonarr/Radarr-compatible naming.

TV downloads default to **entire series**; single episodes and single seasons are opt-in flags. Monitored shows continue to be checked on a daemon tick and new episodes are downloaded automatically as they air. English subtitles are fetched by default and placed alongside the media file when not already present in the torrent.

No GUI, no TUI in v1. Terminal output only, with an optional `--json` flag for machine-readable output. Ships with a `run.bat` that bootstraps the environment via `uv` and launches the app on Windows.

## Requirements

### R1 — CLI surface and configuration

- Installable Python package named `arr` with a console entry point `arr = arr.cli:app` (via `typer`).
- Package manager is **`uv`**, explicitly. No `pip`-based workflows in docs, scripts, or CI. `uv.lock` is committed.
- Commands:
  - `search movie <query>`, `search tv <query> [-s N] [-e N]`
  - `download movie <query> [--pick N | --auto]`
  - `download tv <query> [-s N] [-e N] [--pack] [--pick N | --auto]`
  - `series add <query>`, `series list`, `series remove <id>`, `series check <id>`
  - `queue`, `status <id>`, `cancel <id>`, `import <id>`
  - `daemon`, `config`, `version`
- `download tv <query>` with no `-s`/`-e` downloads the **entire series** (all seasons, all episodes). `-s N` restricts to one season. `-s N -e M` restricts to one episode. The chosen scope is printed before any download starts and confirmed unless `--yes` is passed.
- `--auto` selects the top-ranked release without prompting.
- `--json` emits structured output on every command that returns data.
- Exit codes: `0` success, `1` runtime error, `2` usage error, `3` no results, `4` dependency unavailable (transmission/TMDB).
- Config file at `%APPDATA%\arr\config.toml` on Windows and `$XDG_CONFIG_HOME/arr/config.toml` (default `~/.config/arr/`) on Linux/macOS. Override with `--config`. `config init` writes a documented template.
- Config keys: `tmdb_api_key`, `opensubtitles_api_key`, `download_root`, `library_root`, `transmission_rpc_host`, `transmission_rpc_port`, `transmission_rpc_user`, `transmission_rpc_pass`, `transmission_download_dir`, indexer base URLs, quality profile, seeding policy, per-indexer rate limits, User-Agent, `subtitle_languages` (default `["en"]`), `subtitles_enabled` (default `true`), `subtitles_forced_only` (default `false`), `max_concurrent_downloads` (default `3`), `prefer_season_packs` (default `true`), `monitor_poll_interval_minutes` (default `30`), `monitor_lookahead_days` (default `7`).
- Secrets never logged; `config show` redacts `tmdb_api_key`, `opensubtitles_api_key`, and RPC password unless `--show-secrets`.
- TOML parsing via stdlib `tomllib` on Python 3.11+; `tomli` backport on 3.10.

### R2 — Torrent engine (do not implement one)

- Manage `transmission-daemon` as a child process: start, health-check over RPC, graceful stop, stale-lock / `--port` conflict recovery.
- All torrent operations shell out to `transmission-remote` or hit the Transmission RPC directly via `httpx`: add magnet, list, per-torrent status, remove, remove-and-delete.
- Detect a missing `transmission-daemon` binary and fail with exit code `4` and an actionable install message.
- Support `transmission-remote` on `PATH` and a `--transmission-remote <path>` override. On Windows, also probe `%ProgramFiles%\Transmission\`.
- Enforce `max_concurrent_downloads`: when the limit is reached, queued downloads wait until a slot frees. This is required for whole-series downloads, which enqueue many torrents at once.

### R3 — Metadata resolution

- Resolve free-text queries to canonical IDs via TMDB before searching indexers: `title`, `year`, `imdb_id`, `tmdb_id`, `tvdb_id` where available.
- For TV, resolve `show → seasons → episodes` and carry season and episode numbers through the pipeline. The show object must include `status` (`Returning Series`, `Ended`, `Canceled`, …) and each episode must include `air_date`, `season_number`, `episode_number`, and `name`.
- Cache TMDB responses on disk with a TTL (default 24h). Episode lists for `Returning Series` use a shorter TTL (default 6h) so monitoring picks up newly announced episodes promptly.
- If TMDB is unreachable and no cache entry exists, degrade to free-text indexer search and warn on stderr; do not hard-fail.

### R4 — Indexer adapters

Define one adapter interface implemented by three adapters:

```python
class Adapter(Protocol):
    name: str
    def supports(self, media_type: MediaType) -> bool: ...
    async def search(self, q: Query) -> list[Release]: ...
```

- **YTS** (`movie`): `GET /api/v2/list_movies.json?query_term=<q>`, `GET /api/v2/movie_details.json?movie_id=<id>`. Map `torrents[]` (`hash`, `quality`, `type`, `size_bytes`, `seeds`, `peers`) to `Release`. Build the magnet from `hash` plus configured trackers.
- **EZTV** (`tv`): `GET /api/get_torrents?imdb_id=<tt>&limit=N`. Map `title`, `magnet`, `seeds`, `peers`, `size_bytes`, `season`, `episode`.
- **Nyaa** (`tv`, anime): `GET /?page=rss&q=<q>&c=1_2&f=0`. Parse the `nyaa:` namespace for `seeders`, `leechers`, `size`, `infoHash`; take the magnet from `<link>`. If a required field is absent from RSS, fall back to the HTML table scrape for that field only.
- A single `MediaType` + `Query` fans out to every adapter that `supports` the type, concurrently via `asyncio.gather` with a per-adapter timeout. One adapter erroring does not fail the search; partial results are returned with a stderr warning.
- All base URLs are config-driven with sane defaults; no domain is hardcoded outside the default config template.

### R5 — Release parsing and ranking

- Parse release titles with `guessit` into: `title`, `year`, `season`, `episode`, `resolution`, `source`, `codec`, `group`, `is_pack`, `is_proper`, `is_repack`. Do not hand-roll regexes for this.
- Hard filters before scoring, all configurable:
  - reject `CAM`, `TS`, `HDTS`, `TC`, `R5`, `sample`, `password`
  - reject seeders below `min_seeders` (default `1`)
  - reject resolutions outside the configured allowlist
  - reject sizes outside `min_size`/`max_size` for the media type
  - reject TV releases whose parsed season/episode do not match the query, unless the release is a season pack and the current scope permits it (R11)
- Ranking, deterministic and reproducible:
  - primary sort: seeders descending
  - then: resolution preference rank from the quality profile
  - then: source preference (`BluRay` > `WEB-DL` > `WEBRip` > `HDTV`)
  - then: codec preference from the quality profile
  - then: smaller size wins (avoid oversized remuxes on ties)
  - final tiebreak: infohash ascending, so runs are stable
- `--explain` prints the applied filters and the score components for each candidate. Required for debugging ranking regressions.

### R6 — Download orchestration

- Deduplicate by infohash against a local SQLite `downloads` table before adding; re-adding a known infohash is a no-op with a warning unless `--force` is passed.
- Deduplicate at the **episode** level too: an episode already `imported` is never re-downloaded unless `--force` is passed. This is what makes whole-series and monitoring runs idempotent.
- Add magnets with an explicit download directory under `downloads/<type>/.incomplete/`.
- Respect `max_concurrent_downloads`. Queued torrents are added to Transmission in a stopped state and started when a slot frees.
- Poll RPC until each torrent reaches `seeding` or `completed`, with a configurable poll interval and a `--no-wait` mode that returns immediately.
- Record state transitions (`queued`, `added`, `downloading`, `completed`, `imported`, `failed`, `skipped`) with timestamps in SQLite.
- `queue` lists in-flight, queued, and recently completed downloads. `status <id>` shows detail. `cancel <id>` removes the torrent and optionally deletes data.

### R7 — Import and library layout

Final library layout is exactly:

```
downloads/
  movies/
    <Title> (<Year>)/
      <Title> (<Year>).<ext>
      <Title> (<Year>).en.srt
  tv-shows/
    <Show> (<Year>)/
      Season 01/
        <Show> - S01E01 - <Episode Title>.<ext>
        <Show> - S01E01 - <Episode Title>.en.srt
```

- Staging lives in `downloads/movies/.incomplete/` and `downloads/tv-shows/.incomplete/` and is never scanned as library.
- Naming templates must be Sonarr/Radarr-compatible so Plex and Jellyfin identify files without manual matching.
- Import algorithm:
  1. Resolve the completed torrent's content path.
  2. Enumerate media files; ignore `Sample/`, `Extras/`, `*.nfo`, `*.txt`, `*.url`, and `.DS_Store` when selecting the primary file.
  3. Compute the destination path from the naming template.
  4. Attempt a hardlink. On `OSError` with `errno.EXDEV` (cross-device) or any hardlink failure, fall back to copy, then to move only if `import_mode = "move"` is configured.
  5. Handle collisions: if the destination exists, skip when the existing file's size and infohash match, otherwise append `.1`, `.2`, … and warn. `--overwrite` replaces.
  6. Move sibling subtitles (`.srt`, `.ass`, `.sub`) and rename them to `<media basename>.<lang>.srt` so Plex/Jellyfin pick the correct language track (R12).
  7. Handle multi-file and season-pack torrents by importing each episode into its correct `Season NN` directory.
  8. Handle absolute-numbered anime (`S01E1000` vs `1000`) by preserving the source numbering in v1 and warning; do not attempt to remap.
- Import is idempotent: re-running `import <id>` on an already-imported torrent verifies the destination and exits `0` without duplicating.

### R8 — Seeding policy

- Configurable `seeding_policy` with modes:
  - `ratio` — stop and optionally remove when `seed_ratio` is met
  - `time` — stop after `seed_time_hours`
  - `manual` — never auto-remove
  - `remove_on_import` — remove the torrent immediately after a successful **copy** import
- Hardlink imports leave the torrent data in place so seeding can continue; the CLI must print this trade-off explicitly when it hardlinks and the policy is not `remove_on_import`.
- `remove_on_import` is rejected in combination with hardlink mode (it would delete the library's only copy); the CLI must refuse and explain why.
- Policy evaluation runs on `queue` and on a `daemon` tick.
- For whole-series downloads, the trade-off notice prints once per run, not once per torrent.

### R9 — Robustness, rate limits, and legal posture

- **Domain churn**: every indexer base URL is config-driven. A response that does not match the expected schema produces a distinct error naming the adapter and the URL, not a generic parse failure.
- **Rate limits / Cloudflare**: per-indexer minimum request interval, exponential backoff with jitter on `429`/`503`, a configurable User-Agent, and an on-disk response cache with TTL for search and metadata calls.
- **Timeouts**: every outbound HTTP call has an `httpx` timeout; adapter fan-out has an overall deadline; neither blocks the CLI indefinitely.
- **No auth bypass**: the app must not solve captchas, bypass Cloudflare challenges, or authenticate to private trackers. Public read-only endpoints only. OpenSubtitles uses its official API key flow and does not scrape the website.
- **Legal**: no bundled indexer lists, no bundled trackers beyond what the indexers themselves return, no hosted content, no seedbox functionality. Ship a `LEGAL.md` stating the tool is a client for user-chosen public indexers and that the user is responsible for compliance. No telemetry.
- **Daemon lifecycle**: handle a stale `transmission-daemon` lock file, a port already in use, and RPC auth failures with distinct exit codes and remediation hints.
- **Idempotency**: all commands safe to re-run, including the monitor tick.

### R10 — Tests and documentation

- Unit tests with `pytest` for: release parsing, ranking (with fixed fixtures, asserting stable order), each adapter against recorded HTTP fixtures (via `respx`), import path computation, collision handling, naming templates, episode-dedup logic, monitor scheduling, subtitle selection, and subtitle filename generation.
- Integration tests using `tmp_path` and fake torrent payloads; no network, no real daemon required. Covers the import pipeline end to end including subtitle placement.
- Optional tests marked `@pytest.mark.integration` that exercise a real `transmission-daemon` on `localhost`; deselected by default.
- `README.md` with install, `config init`, first-run walkthrough, and the full command reference.
- `LEGAL.md` as described in R9.
- `GOTCHAS.md` documenting known failure modes and their handling.

### R11 — Series-level downloads and monitoring

- `download tv <query>` without `-s`/`-e` resolves the whole series via TMDB, enumerates every episode across every season, filters out episodes already `imported`, and enqueues the remainder respecting `max_concurrent_downloads`.
- Scope flags:
  - `-s N` → one season
  - `-s N -e M` → one episode
  - `--pack` → prefer season packs over per-episode releases (default governed by `prefer_season_packs`)
- Season-pack handling: if a pack is chosen, it satisfies every episode in its season; episodes covered by an imported pack are marked `imported` in the episode table without individual torrents.
- `series add <query>` resolves the show via TMDB, adds it to a `monitored_series` table with `tmdb_id`, `imdb_id`, `title`, `status`, `last_checked_at`, and the preferred quality profile, then performs an initial whole-series download.
- `series list` shows each monitored show, its TMDB status, the last check time, the next known air date, and the count of imported/missing episodes.
- `series remove <id>` stops monitoring and optionally removes downloaded files with `--delete-files`.
- `series check <id>` forces an immediate check for that show, bypassing the normal tick.
- `arr daemon` runs a loop on `monitor_poll_interval_minutes`:
  1. For each monitored series, refresh TMDB episode data (respecting the shorter episode TTL).
  2. Select episodes whose `air_date` is today or earlier, or within `monitor_lookahead_days` and marked as available on the indexer.
  3. Exclude episodes already `imported` or currently `downloading`.
  4. Search → rank → enqueue respecting `max_concurrent_downloads`.
  5. Import completed downloads and record state.
  6. Apply seeding policy.
  7. Sleep until the next tick. SIGINT/SIGTERM exits cleanly after the current tick.
- The monitor tick is idempotent: running it twice in a row enqueues nothing the second time.
- If an indexer is down during a tick, the affected episodes are recorded as `retry_pending` and retried on the next tick; a single indexer failure never halts the whole loop.
- Ended/canceled series are still monitored but the tick naturally finds nothing new; `series list` marks them clearly. A config option `unmonitor_ended_series` (default `false`) controls whether ended shows are auto-removed from monitoring.

### R12 — Subtitles (English by default)

- Default behavior: every movie and TV episode import attempts to leave an English subtitle file next to the media file named `<media basename>.en.srt`.
- Source priority:
  1. **Embedded or sibling subtitles in the torrent.** Sibling `.srt`/`.ass`/`.sub` files are imported and renamed. `.ass` and `.sub` are converted to `.srt` only if `ffmpeg` is available; otherwise they are copied with their original extension and renamed to `<basename>.en.<ext>`.
  2. **OpenSubtitles API** if `opensubtitles_api_key` is configured and no English subtitle was found in the torrent. Uses the official REST API with the configured key.
  3. **Skip with a warning** if neither source yields a subtitle. The media file is still imported; missing subtitles are recorded in the `subtitles` table with state `missing`.
- Language selection is driven by `subtitle_languages` (default `["en"]`). Multiple languages produce multiple files (`<basename>.en.srt`, `<basename>.es.srt`).
- `subtitles_forced_only` (default `false`) filters OpenSubtitles results to forced subtitles only when enabled.
- Subtitle lookup for TV is per-episode: uses `imdb_id` + season + episode. For movies: `imdb_id` or `tmdb_id`.
- If OpenSubtitles returns multiple candidates, pick by (hearing-impaired match to config) → (download count desc) → (release name similarity to the torrent name desc) → (upload date desc). Deterministic.
- Subtitle fetch runs **after** a successful import so a failure never blocks the media file from being available.
- `subtitles_enabled = false` disables the entire subsystem, including OpenSubtitles lookups and sibling-subtitle renaming.
- The `subtitles` table in SQLite records: media path, language, source (`embedded`, `sibling`, `opensubtitles`, `missing`), state, and the OpenSubtitles subtitle ID when applicable.
- Respect the OpenSubtitles daily download quota; on quota exhaustion, record `quota_exceeded` and retry on the next daemon tick rather than failing the import.

### R13 — Windows launcher and `uv`-based bootstrap

- Repo root ships `run.bat` that, on a clean Windows machine:
  1. Checks for `uv` on `PATH`. If missing, prints the install command (`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`) and exits non-zero with a `pause` so the message is readable.
  2. Checks for a suitable Python via `uv python find 3.11` or falls back to letting `uv` manage its own Python.
  3. Runs `uv sync` in the repo root. `uv` creates and manages `.venv` itself; `run.bat` does not call `python -m venv` or `pip` directly.
  4. Runs `uv run arr %*` to forward all arguments to the CLI.
  5. With no arguments, runs `uv run arr --help`.
  6. On non-zero exit, prints the exit code and `pause`.
- `run.bat` must be idempotent; `uv sync` is a no-op when the lockfile and environment are already current.
- A matching `run.sh` (Linux/macOS) mirrors the behavior and is documented in `README.md`.
- `run.bat` must not require admin rights and must not write outside the repo directory, `uv`'s own cache directory, and the user's config directory.
- All install and dev instructions in `README.md` use `uv` (`uv sync`, `uv run pytest`, `uv run ruff check .`, `uv run mypy arr`). No `pip install` commands appear anywhere in the repo, including CI configs.
- `uv.lock` is committed and kept in sync with `pyproject.toml`.

## Definition of Done

- [x] R1 implemented — CLI, exit codes, config, redaction, TV scope flags
- [x] R2 implemented — transmission lifecycle + RPC + concurrency limit
- [x] R3 implemented — TMDB resolve with cache, short episode TTL
- [x] R4 implemented — YTS, EZTV, Nyaa adapters behind one interface
- [x] R5 implemented — parser, hard filters, deterministic ranking, `--explain`
- [x] R6 implemented — infohash + episode dedupe, queue, state machine
- [x] R7 implemented — library layout, hardlink→copy fallback, collision handling, subtitle-aware naming
- [x] R8 implemented — seeding policy modes and hardlink guard
- [x] R9 implemented — config-driven URLs, backoff, caching, timeouts, no auth bypass, `LEGAL.md`, daemon failure handling
- [x] R10 implemented — pytest suite, fixture-based adapter tests, integration import test, README, LEGAL, GOTCHAS
- [x] R11 implemented — whole-series download, `series add/list/remove/check`, `daemon` monitor loop, idempotent ticks, retry_pending handling
- [x] R12 implemented — sibling/embedded subtitle import, OpenSubtitles fallback, `.en.srt` naming, quota handling, `subtitles` table
- [x] R13 implemented — `run.bat` + `run.sh` use `uv sync` and `uv run`, idempotent, pause on error
- [x] `uv run pytest` passes with no network access
- [x] `uv run ruff check .` and `uv run mypy arr` pass
- [ ] End-to-end smoke: `run.bat download movie "Inception" --auto` imports to `downloads/movies/Inception (2010)/` with an `.en.srt` subtitle present or a recorded `missing` state
- [ ] End-to-end smoke: `run.bat download tv "Breaking Bad"` downloads and imports the entire series into `downloads/tv-shows/Breaking Bad (2008)/Season NN/`
- [ ] End-to-end smoke: `run.bat series add "Some Airing Show"` adds monitoring, and a subsequent `run.bat daemon` tick enqueues only newly aired episodes
- [ ] Re-running any of the above exits `0` without duplicating
- [x] Existing functionality still works
- [x] No obvious regressions remain

## Constraints

- **Language**: Python 3.11+ (3.10 supported via `tomli` backport).
- **Package manager**: **`uv` only.** `pyproject.toml` + `uv.lock`. No `pip`, no `poetry`, no `pipenv`, no `conda` anywhere in the repo, docs, scripts, or CI. `run.bat` and `run.sh` call `uv sync` and `uv run`.
- **Runtime dependency**: `transmission-daemon` and `transmission-remote`. `ffmpeg` is optional and only used for `.ass`/`.sub` → `.srt` conversion; without it, subtitle files are copied with their original extension.
- **Third-party libraries**: `typer`, `httpx`, `pydantic`, `guessit`, `rich`, `tomli` (3.10 only). Stdlib `sqlite3` for storage. Dev: `pytest`, `respx`, `ruff`, `mypy`. No `requests` (use `httpx`), no ORM.
- **No GUI, no TUI** in v1. CLI output plus `--json` only.
- **No embedded torrent client.** Do not implement DHT, trackers, or peer wire protocol. Transmission owns that.
- **No bundled indexers, trackers, or content.** Indexers are user-configured public endpoints.
- **No authentication bypass** of any kind, including captcha solving and Cloudflare circumvention. OpenSubtitles uses the official API only.
- **No telemetry, no phone-home**, no analytics.
- **Library root is exactly** `downloads/movies` and `downloads/tv-shows`; staging lives in `.incomplete/` subdirectories and is never treated as library content.
- **Naming must be Sonarr/Radarr-compatible**; Plex/Jellyfin must identify imported files and subtitles without manual matching.
- Secrets (TMDB key, OpenSubtitles key, RPC password) must never appear in logs, `--json` output, or committed files.
- All network calls must be cancellable with timeouts.
- **Subtitles default to English.** Disabling them requires `subtitles_enabled = false` in config.
- **TV defaults to whole-series.** Single episode requires explicit `-s N -e M`.
- Out-of-scope for v1, explicitly: multi-user, VPN kill switch, quality upgrades of existing files, anime absolute-number remapping, web UI, private trackers, non-English subtitle UI, subtitle translation.
