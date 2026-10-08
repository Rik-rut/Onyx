# Autonomous Agent State

Status: IN_PROGRESS

Iteration: 19

Current Objective:
Enforce `max_concurrent_downloads` (R2/R6) so queued downloads wait until a slot frees, which whole-series downloads require.

Completed:
- (Iteration 17) No-API-key migration (TVMaze/IMDb/Subscene/YIFY) and live-smoke bug fixes.
- (Iteration 18) Wired real orchestration: whole-series/season/episode enqueue, movie/episode/season-pack import with subtitles, synchronous daemon loop, `series_add` initial download, `series_remove --delete-files`, `series_list` counts.
- (Iteration 19) Fixed EZTV returning unrelated latest torrents for unmatched queries: added a config-scoped title-relevance gate (`title_strict_indexers`, default `["eztv"]`).
- (Iteration 20) Implemented the `max_concurrent_downloads` gate (was defined but never enforced):
  - Added `RpcClient.stop`, status constants (`STOPPED`/`DOWNLOAD`/`SEED`), and pure helpers `is_active_torrent`, `active_count`, `is_complete_torrent`, `plan_slots` in `transmission/process.py`.
  - `_enqueue_episodes` now decides all releases first, reads active torrent count, adds with `paused=True` once the limit is reached, records `queued` vs `added`, then `_promote_queued` starts queued torrents when a slot frees.
  - `download_movie` adds paused when at the limit and promotes before polling; `run_daemon` calls `_sync_rpc_state` → `_promote_queued` (via `asyncio.run`) → import → seeding policy each tick.
  - Fixed a real bug the new tests caught: `is_complete_torrent` treated status DOWNLOAD(4) as complete; it now requires SEED(6) or `percentDone>=1.0`.
  - Fixed nested `asyncio.run` in `_promote_queued` (was firing from inside the enqueue coroutine) by making it a coroutine.
- Added `tests/test_concurrency.py` (7 tests) and a pipeline test proving the 2nd episode is queued when `max_concurrent_downloads=1`.

Current Work:
Executing autonomous iteration.

Last Test Result:
PASSED

Current Problem:
The three end-to-end download smokes in TASK DoD (lines 233-236) require transferring real copyrighted media through a running transmission-daemon; not performed by the agent. All logic paths are verified offline and with stubbed RPC; a real `transmission-daemon` start → RPC handshake → stop was previously verified.

Next Action:
Human runs the E2E download smokes against a running transmission-daemon, then marks DoD 233-236 and sets Status: COMPLETE.

Last Updated:
2026-10-08T14:49:27.094741+00:00
