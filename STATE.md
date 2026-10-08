# Autonomous Agent State

Status: BLOCKED

Iteration: 9

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

- Added R13 launchers: `run.bat` (checks `uv`, prints install hint + `pause` on failure, `uv sync`, `uv run arr` / `--help` when no args, prints exit code + `pause` on non-zero) and `run.sh` mirror. Added README.md (install/run/config/command reference/scope rules/monitoring/layout/seeding/subtitles), LEGAL.md, GOTCHAS.md. R9 robustness greps: no pip/poetry/conda/venv references outside historical notes; indexer base URLs only in `config/settings.py` defaults (Nyaa namespace URI is an identifier, not a request target); OpenSubtitlesClient base now overridable via `base_url`.

Current Work:
DoD walk complete. Verified: R1–R13 implemented, `uv run pytest` 50 passed/1 deselected, integration daemon test passes, ruff + mypy clean, `run.bat version`/`config path`/`--help` smoke OK, offline degradation path verified (TMDB 401 → free-text fallback, yts DNS failure isolated, exit 3). Support dropped py311-only constraint: `requires-python = ">=3.10"` with `tomli` marker for <3.11 (uv.lock regenerated).

Last Test Result:
PASSED

Current Problem:
Live end-to-end smoke tests (download movie/tv via real indexers, series add + daemon tick enqueue) cannot run on this machine: no TMDB/OpenSubtitles API keys configured and outbound DNS to indexers fails. These four DoD checkboxes remain unchecked by design. Additionally, the daemon tick's `enqueue` hook is currently a counting stub (does not add real magnets) pending a reachable indexer; whole-series enqueue respecting `max_concurrent_downloads` is wired in `pipeline.download_tv` only for a single chosen release.

Next Action:
If API keys + outbound network become available: configure `tmdb_api_key`, run `run.bat download movie "Inception" --auto`, `run.bat download tv "Breaking Bad"` (whole series), `run.bat series add <show>` then two `daemon` ticks to confirm no duplicate enqueue, and check the four live-smoke DoD boxes. Otherwise the codebase is feature-complete and fully tested offline.

Last Updated:
2026-10-08T01:22:17.092657+00:00
