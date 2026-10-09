# Implementation Plan

Status: COMPLETE (All core requirements and Interactive CLI Mode verified)

## Phase 2 (Completed): Interactive CLI Application (R14)

### Architecture Decision: Interactive CLI Mode via `rich`
- **Objective**: Transform `run.bat` into a full interactive CLI app when launched without arguments (or with `arr interactive`).
- **Core Tooling**: Use `rich` (already present in `pyproject.toml`) for console layout, panels, tables, prompts, and status indicators.
- **Backward Compatibility**: Keep non-interactive CLI flags working identically when arguments are provided to `run.bat` (e.g. `run.bat search movie "Inception"`).
- **Separation of Concerns**: Created `src/arr/interactive/` with dedicated modules for UI components, TV flow, Movie flow, Queue flow, Daemon status, Config view, and Series management flow, keeping `src/arr/pipeline.py` and `src/arr/cli.py` clean.

### Phase 2 Implementation Steps (All Completed & Verified)

1. **Created `src/arr/interactive/ui.py`**:
   - Reusable Rich console, header banners, styling themes.
   - Formatted release results table (`render_releases_table`).
   - Formatted queue and torrent status table (`render_queue_table`).
   - Formatted monitored series table (`render_series_table`).
   - Prompt helper functions: text prompt with back/cancel support, choice prompt with validation, confirmation prompt.

2. **Created `src/arr/interactive/tv.py`**:
   - Interactive TV search prompt.
   - TVMaze resolution & show overview panel (title, year, premiered, status, season count, episode count).
   - Scope selector:
     - `1`: Entire series (all seasons, season-pack priority)
     - `2`: Specific season (prompt for season number)
     - `3`: Specific episode (prompt for season & episode)
     - `4`: Direct indexer query (bypass TVMaze)
   - Search indexers, rank results, render Rich results table.
   - Release selector: pick index `[0-N]`, `auto`, `explain <#>`, or `b` (back).
   - Enqueue and kick off download via Transmission RPC; show live feedback.

3. **Created `src/arr/interactive/movie.py`**:
   - Interactive movie search prompt.
   - IMDb resolution (title, year, IMDb ID).
   - Search indexers, rank results, render Rich results table.
   - Release selector: pick index `[0-N]`, `auto`, `explain <#>`, or `b` (back).
   - Enqueue and kick off download via Transmission RPC.

4. **Created `src/arr/interactive/queue.py`**:
   - Pull active downloads and transmission torrents.
   - Render styled status table with progress %, state, speed, and ETA.
   - Submenu: refresh view, cancel download (optional delete), manual import.

5. **Created `src/arr/interactive/series.py`**:
   - List monitored series from database with status and missing episode counts.
   - Add new series to monitoring (search TVMaze, save to DB, initial download).
   - Force check episodes (`series check`).
   - Remove series (optional file deletion).

6. **Created `src/arr/interactive/daemon_view.py` & `src/arr/interactive/config_view.py`**:
   - Transmission daemon status view, connection health check, and binary diagnostics.
   - Configuration viewer displaying active settings and redacted values.

7. **Created `src/arr/interactive/app.py` & `src/arr/interactive/__init__.py`**:
   - Main menu loop:
     - [1] Search & Download TV Shows
     - [2] Search & Download Movies
     - [3] Manage Monitored Series
     - [4] Queue & Active Downloads
     - [5] Transmission Daemon Status
     - [6] Configuration & Settings
     - [0] Exit
   - Graceful `KeyboardInterrupt` handling.

8. **Wired CLI Entry Point (`src/arr/cli.py`)**:
   - Registered `@app.command("interactive")`.
   - Updated `@app.callback(invoke_without_command=True)` to run interactive mode when invoked without a subcommand.

9. **Updated Launchers (`run.bat` & `run.sh`)**:
   - In `run.bat`, updated no-argument execution to run `"%UV%" run arr interactive` and retain exit code.
   - In `run.sh`, updated no-argument execution to run `uv run arr interactive`.

10. **Automated Tests (`tests/test_interactive.py`)**:
    - 15 unit and integration tests verifying navigation, TV flow, Movie flow, Queue flow, Daemon status, Config view, and graceful exit.
    - Verified table generation with various releases.
    - Verified error recovery on invalid choices and keyboard interrupts.

11. **Full Verification**:
    - `uv run pytest` (129 passed, 1 deselected; 1 real daemon integration test passed).
    - `uv run ruff check .` and `uv run mypy arr` pass with zero errors across 44 files.
    - Smoke tested `echo 0 | run.bat` exiting 0.

---

## Phase 1 (Completed): Architecture Decision: No API Keys

**Decision**: Remove TMDB and OpenSubtitles entirely. Replace with:
- **TVMaze** (free REST API, no auth) for TV metadata
- **IMDb scraping** via `curl_cffi` for movie metadata
- **Subscene** scraping via `curl_cffi` for subtitles (primary)
- **YIFY Subtitles** scraping via `curl_cffi` for subtitles (fallback)

**Rationale**: User does not want to manage API keys. TVMaze provides equivalent TV metadata (search, episodes, external IDs) with no auth. IMDb/Subscene/YIFY are scraped with browser impersonation to avoid TLS-fingerprint blocks.

**Trade-offs**:
- Scraping is more fragile than REST APIs (HTML structure changes, blocks)
- Graceful degradation: if scraping fails, fall back to free-text search / skip subtitles
- `tmdb_id` field name retained in DB/models for compatibility (stores TVMaze IDs)

## Steps

1. **Add `curl_cffi` + `selectolax` dependencies** to `pyproject.toml`.
   - `curl_cffi>=0.7` — browser-impersonation HTTP client
   - `selectolax>=0.3` — fast HTML parser (lighter than BeautifulSoup)
   - Run `uv lock` to update `uv.lock`.

2. **Create `src/arr/metadata/tvmaze.py`** — TVMaze REST client.
   - Same public methods as old `TmdbClient`: `search_tv`, `tv_details`, `tv_external_ids`, `season`, `full_series`
   - Uses `httpx` + disk cache (same pattern as current TMDB client)
   - Maps TVMaze fields → existing `Series`/`Episode` models
   - `id` → `tmdb_id`, `name` → `title`, `premiered` → `year`, `externals.imdb` → `imdb_id`
   - Rate limit: 20 calls/10s per IP — handle 429 with backoff
   - Tests: `tests/test_tvmaze.py` using `respx` to mock REST API

3. **Create `src/arr/metadata/imdb.py`** — IMDb scraping client.
   - `search_movie(query)` — scrape `https://www.imdb.com/find/?q=<query>` with `curl_cffi` + `impersonate="chrome"`
   - `movie_details(imdb_id)` — scrape `https://www.imdb.com/title/<id>/`
   - Parse HTML with `selectolax`
   - Returns dict with `id`, `title`, `year`, `imdb_id`
   - On failure: raise `MetadataError` (caught by pipeline, degrades to free-text)
   - Tests: `tests/test_imdb.py` mocking `curl_cffi` responses

4. **Create `src/arr/subtitles/subscene.py`** — Subscene scraping client.
   - Same interface as `OpenSubtitlesClient`: `search(...)`, `download_link(file_id)`
   - Search by title or IMDB ID + season/episode
   - Parse results with `selectolax`
   - Returns `list[SubtitleCandidate]` (same dataclass)
   - Tests: `tests/test_subscene.py` mocking `curl_cffi` responses

5. **Create `src/arr/subtitles/yify.py`** — YIFY Subtitles scraping client.
   - Same interface as Subscene
   - Fallback when Subscene fails or returns no results
   - Tests: `tests/test_yify.py` mocking `curl_cffi` responses

6. **Update `src/arr/config/settings.py`** — remove API keys, add new source URLs.
   - Remove from `DEFAULTS`: `tmdb_api_key`, `tmdb_base_url`, `opensubtitles_api_key`
   - Add to `DEFAULTS`: `tvmaze_base_url`, `imdb_base_url`, `subscene_base_url`, `yify_subtitles_base_url`
   - Update `SECRET_KEYS`: remove `tmdb_api_key`, `opensubtitles_api_key`
   - Update `CONFIG_TEMPLATE`: remove API key lines, add new source URL comments

7. **Update `src/arr/pipeline.py`** — use new clients.
   - Replace `TmdbClient` import with `TvmazeClient` + `ImdbClient`
   - `search()`: TV → TVMaze resolve; Movie → IMDb scrape; degrade to free-text on failure
   - `series_add()`: use `TvmazeClient.full_series()`
   - `series_check()`: use `TvmazeClient.full_series()`
   - `run_daemon()`: wire `series_fetcher` to `TvmazeClient`, implement real `enqueue` (add magnets via RPC)

8. **Update `src/arr/subtitles/service.py`** — use Subscene + YIFY.
   - Replace `OpenSubtitlesClient` with `SubsceneClient` (primary) + `YifySubtitlesClient` (fallback)
   - Try Subscene first; on failure, try YIFY; on failure, record `missing`
   - Remove `QuotaExceeded` handling (no API quota with scraping)
   - Update `subtitles` table source values: `subscene`, `yify` instead of `opensubtitles`

9. **Remove old files**:
   - Delete `src/arr/metadata/tmdb.py`
   - Delete `src/arr/subtitles/opensubtitles.py`
   - Delete `tests/test_tmdb.py`
   - Update `tests/test_subtitles.py` → test Subscene/YIFY instead

10. **Update tests**:
    - `tests/test_tvmaze.py` — respx mocks for TVMaze REST API
    - `tests/test_imdb.py` — mock curl_cffi responses
    - `tests/test_subscene.py` — mock curl_cffi responses
    - `tests/test_yify.py` — mock curl_cffi responses
    - `tests/test_series_monitor.py` — update to use TVMaze mocks
    - `tests/test_subtitles.py` — update to use Subscene/YIFY mocks

11. **Update documentation**:
    - `README.md`: remove API key setup, add scraping sources note
    - `GOTCHAS.md`: add scraping fragility notes
    - `LEGAL.md`: update to mention scraping

12. **Run full verification**:
    - `uv run pytest` — all tests pass
    - `uv run ruff check .` — lint clean
    - `uv run mypy arr` — type check clean
    - Smoke test: `run.bat version`, `run.bat config path`, `run.bat --help`

## Notes

- `curl_cffi` supports Python 3.10+ (matches project requirement)
- `selectolax` is a lightweight HTML parser (similar to lxml, much faster than BeautifulSoup)
- TVMaze API is CC BY-SA licensed — attribution in README
- IMDb/Subscene/YIFY scraping may break if sites change HTML structure — graceful degradation is essential
- The `tmdb_id` field name is kept for DB compatibility but stores TVMaze show IDs
- `curl_cffi` impersonation is used only to avoid TLS-fingerprint blocks, not to solve captchas or bypass Cloudflare challenges

## Gotcha → handling map

- TVMaze rate limit (429) → exponential backoff with jitter
- TVMaze unreachable → stale cache fallback, then free-text search
- IMDb HTML structure change → parsing fails gracefully, free-text fallback
- IMDb blocks scraper → curl_cffi impersonation retry, then free-text fallback
- Subscene HTML structure change → try YIFY, then skip with warning
- YIFY HTML structure change → skip with warning
- Subscene/YIFY rate limit → backoff, record `error`, retry next tick
- EZTV domain churn → config-driven base URL; schema-mismatch error names adapter + URL
- YTS API stability → config-driven; cache responses
- Nyaa Cloudflare / rate limits → min interval, backoff with jitter, User-Agent, on-disk cache
- Nyaa RSS missing fields → per-field HTML scrape fallback only
- Cross-device hardlink failure → `errno.EXDEV` detection, copy fallback
- Multi-file / season-pack torrents → per-episode distribution into `Season NN`
- Sample/extras/junk files → filtered during content enumeration
- Subtitle siblings → renamed to `<basename>.<lang>.<ext>`
- `.ass`/`.sub` without `ffmpeg` → copied with original extension
- Missing subtitles → media still imported; `missing` recorded in `subtitles` table
- Destination collisions → size+infohash match = skip; else suffix; `--overwrite` replaces
- Seeding after import → hardlink keeps data for seeding; trade-off printed once per run
- Sonarr/Radarr naming → templates fixed and covered by unit tests
- transmission-daemon lifecycle → stale lock, port in use, auth failure each mapped to exit code 4
- Duplicate downloads → infohash dedupe + episode dedupe in SQLite, `--force` override
- Monitor tick re-enqueue → episode-level dedupe plus `episodes.state` check
- Indexer down during a tick → `retry_pending`, loop continues
- Anime absolute numbering → preserved with a warning; remapping out of scope
- Secrets in logs → redaction in logger and `config show`
- `run.bat` idempotency → `uv sync` is a no-op when current
- `uv` missing → `run.bat` prints install command and exits with readable message
