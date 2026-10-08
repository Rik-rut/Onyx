# Autonomous Agent State

Status: IN_PROGRESS

Iteration: 17

Current Objective:
Wire the previously-stubbed download/import/monitor orchestration (R6/R7/R11) so the CLI actually enqueues whole series, imports completed downloads, runs the monitor's download step, and honors `--delete-files`.

Completed:
- (Iteration 17) Completed the no-API-key migration (TVMaze/IMDb/Subscene/YIFY), deleted TMDB/OpenSubtitles, fixed live-smoke bugs (EZTV `get-torrents`, YTS `yts.lt`, YIFY dedupe, IMDb suggestion fallback, `--config` Path coercion, `--explain` wiring), and fixed the ruff `extend-exclude` that hid 55 lint errors in `src/arr`.
- Implemented real orchestration in `src/arr/pipeline.py`:
  - `_fan_out` — shared concurrent adapter fan-out with per-adapter timeout.
  - `_enqueue_episodes` — resolves + ranks one best release per missing episode, dedupes by infohash and DB state, enqueues via RPC, records `downloads` + `episodes` state. Idempotent.
  - `_enqueue_series_query` / `_enqueue_tv_scope` / `_enqueue_tv_scope_by_search` — whole-series and season/episode scopes, with free-text fallback when TVMaze is unavailable.
  - `download_tv` now performs whole-series (default) or `-s`/`-s -e` scope enqueue instead of adding one release.
  - `series_add` performs the required initial whole-series download.
  - `_import_record` — real movie/episode/season-pack import with subtitle placement; `import_download` now imports and is idempotent; `download_movie` imports after polling.
  - `run_daemon` rewritten as a synchronous monitor loop: tick → `_sync_rpc_state` → `_poll_and_import` → `_apply_seeding_policy`; `enqueue` callback actually adds magnets.
  - `series_remove --delete-files` deletes the show's library folder; `series_list` reports pending/missing episode counts.
- Extended `db.py`: `_migrate()` adds `year`/`imdb_id`/`episode_title` columns; `add_download` persists them.
- Extended `importer/layout.py`: `find_episode_file`, `matches_episode`, and `import_subtitles(only=...)` for per-episode/pack subtitle placement.
- Added `tests/test_pipeline.py` (7 tests): per-episode enqueue + idempotency, shared-infohash pack dedupe, scope-respects-arg regression, movie import, episode import with subtitle rename, pack distribution, `series_remove --delete-files`.
- Fixed real bug found by live verification: `_enqueue_episodes` ignored its `episodes` argument and re-scoped the entire series (enqueued 15 for a 3-episode request). Now filters the passed scope.

Current Work:
Executing autonomous iteration.

Last Test Result:
PASSED

Current Problem:
The three end-to-end download smokes in TASK DoD (lines 233-236) require transferring real copyrighted media through a running transmission-daemon; not performed by the agent. Live verification was done with a stubbed RPC so no content was downloaded.

Next Action:
Human runs the E2E download smokes against a running transmission-daemon, then marks DoD 233-236 and sets Status: COMPLETE.

Last Updated:
2026-10-08T14:43:52.063773+00:00
