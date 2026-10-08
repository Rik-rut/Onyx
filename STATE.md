# Autonomous Agent State

Status: IN_PROGRESS

Iteration: 6

Current Objective:
Scaffold complete; proceed to release parsing/ranking and core domain wiring.

Completed:
- Inspected repo: no pyproject.toml/src existed; uv 0.12.4 + Python 3.14.6 present; transmission-daemon NOT installed; ffmpeg available via scoop.
- Scaffolded uv package: pyproject.toml (src layout, hatchling), uv.lock via `uv sync`, deps typer/httpx/pydantic/guessit/rich, dev pytest/respx/ruff/mypy.
- Created src/arr package: cli.py (typer stubs for search/download/series/queue/status/cancel/import/daemon/config/version), core/models.py (pydantic domain models + Adapter protocol), config/settings.py (TOML load, defaults, init template, redaction), log.py (stderr logger with secret redaction), exit.py (IntEnum exit codes), pipeline.py (stubbed functions).
- `uv run ruff check .` passes; `uv run mypy arr` passes (root junction `arr` -> src/arr makes the documented command work).
- Implemented `src/arr/core/parsing.py` (guessit-backed parse_release, normalization, hard_filter, deterministic rank(), explain()) and tests/test_parsing_ranking.py (9 tests, all passing).
- Implemented `src/arr/transmission/` (errors + process: find_binary/find_remote/find_daemon with PATH + %ProgramFiles%\Transmission probing, Daemon start/stop, RpcClient add/list/get/remove/start via httpx with session-id handshake and 401->AuthError, ConcurrencyGate semaphore) and tests/test_transmission.py (3 passing, 1 integration deselected).

- Implemented `src/arr/indexers/` (base HttpClient with per-indexer throttle, 429/503 backoff+jitter, TTL disk cache, User-Agent config; yts/eztv/nyaa adapters, SchemaMismatchError naming adapter+URL) and tests/test_indexers.py (5 respx tests passing).
- Implemented `src/arr/metadata/tmdb.py` (search movie/tv, tv_details/external_ids, season episode lists, full_series, disk cache with per-type TTL — 6h for Returning Series season fetches — stale-cache fallback on error) and tests/test_tmdb.py (3 respx tests passing). Added `tmdb_base_url` to config defaults.
- Implemented `src/arr/db.py` SQLite layer (downloads/episodes/events/monitored_series/subtitles tables, infohash dedupe add, episode state upsert, monitored CRUD, subtitle records) and tests/test_db.py (5 tests passing).
- Implemented `src/arr/importer/layout.py` (movie_dest/episode_dest Sonarr+Radarr-compatible naming, junk filtering incl. Sample/extras, media_files/subtitle_files enumeration, import_file hardlink→copy fallback with EXDEV tolerance, collision detection via size+sha1, import_movie/import_episode with sibling subtitle renaming to `<basename>.en.<ext>`, season-pack per-episode import) and tests/test_importer.py (6 tests passing).
- Wired `pipeline.search`: TMDB resolve (best-effort, degrades to free-text with stderr warning) → adapter fan-out via asyncio.gather with 30s per-adapter timeout (per-adapter failure isolated) → parse/filter/rank via `core.parsing` → releases. `--explain` hook prints filter reasons/score components to stderr.
- Implemented `src/arr/seeding.py` (ratio/time/manual/remove_on_import modes, `validate_seeding` refuses remove_on_import+hardlink with explanation, `should_remove` policy evaluator, HARDLINK_NOTICE) and tests/test_seeding.py (5 tests).
- Implemented R11 core: `src/arr/series/orchestration.py` (resolve_scope whole-series/season/episode, seasons_in_scope, needed_episodes dedupe vs downloads/episodes states queued/added/downloading/completed/imported, mark_pack_imported, episodes_in_season) and `src/arr/monitor/loop.py` (episode_airs_within_lookahead, select_airing, idempotent tick with per-series failure isolation, retry_pending on enqueue failure, last_checked updates). tests/test_series_monitor.py (9 tests, all passing).

- Implemented R12 core: `src/arr/subtitles/opensubtitles.py` (OpenSubtitlesClient search/download via official REST + Api-Key auth, SubtitleCandidate, deterministic rank_candidates: hearing-impaired match → download count desc → release-name similarity desc → upload date desc, forced_only filter, QuotaExceeded on HTTP 429) and tests/test_subtitles.py (5 tests, all passing).
- Added `src/arr/subtitles/service.py` (`ensure_subtitles`: sibling-subtitle detection first, `.ass`/`.sub`→`.srt` via ffmpeg when available else copy with original ext, OpenSubtitles fallback, `missing`/`quota_exceeded`/`error` recorded in DB, returns per-language records).
- Implemented the download/monitor pipeline in `src/arr/pipeline.py`: `download_movie` (search→pick/auto→scope print→confirm unless --yes→dedupe via DB→transmission add→optional poll→import→ensure_subtitles→state machine), `download_tv` (scope string printing, candidate list, transmission add), `series_add/list/remove/check` (TMDB resolve + monitored_series CRUD + per-series due-episode count via select_airing), `list_queue/get_status/cancel_download/import_download`, and `run_daemon` (loop over monitor.loop.tick with series_fetcher/enqueue and configurable poll interval). DependencyUnavailable maps to SystemExit(4).

Current Work:
Download/monitor pipeline + subtitle service wired; `arr` CLI loads and `version`/`--help` work. Next: R13 run.bat/run.sh, README/LEGAL/GOTCHAS docs, and the robustness pass (R9 greps for hardcoded domains and pip references).

Last Test Result:
PASSED

Current Problem:
transmission-daemon/transmission-remote not installed on this machine — R2 runtime integration tests and the R13 end-to-end smoke tests will hit exit-code-4 dependency-unavailable handling until Transmission is installed.

Next Action:
Implement R13 (`run.bat` + `run.sh`: uv check, `uv sync`, `uv run arr`, pause on error/no-args help), write README.md/LEGAL.md/GOTCHAS.md, then run the R9 robustness greps (no hardcoded indexer domains, no pip/venv references), and smoke `run.bat` paths that don't need a daemon.

Last Updated:
2026-10-08T01:15:35.091069+00:00
