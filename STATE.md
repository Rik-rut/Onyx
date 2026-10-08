# Autonomous Agent State

Status: IN_PROGRESS

Iteration: 18

Current Objective:
Harden search correctness (indexer result validation) and verify the CLI exit-code contract after the orchestration wiring.

Completed:
- (Iteration 17) No-API-key migration (TVMaze/IMDb/Subscene/YIFY); fixed live-smoke bugs (EZTV `get-torrents`, YTS `yts.lt`, YIFY dedupe, IMDb suggestion fallback, `--config` Path coercion, `--explain`), and fixed the ruff `extend-exclude` hiding 55 lint errors.
- (Iteration 18) Wired real orchestration: whole-series/season/episode enqueue, movie/episode/season-pack import with subtitles, synchronous daemon loop (tick → sync RPC state → import → seeding policy), `series_add` initial download, `series_remove --delete-files`, `series_list` counts; DB migration for `year`/`imdb_id`/`episode_title`; importer helpers. Added `tests/test_pipeline.py`.
- (Iteration 19) Fixed a real search-correctness bug: EZTV silently returns its latest torrents when a query/imdb id does not match, so nonsense queries returned dozens of unrelated releases with exit 0.
  - Added a title-relevance gate to `core.parsing.hard_filter`, applied only to indexers listed in the new `title_strict_indexers` config (default `["eztv"]`) so romanized anime titles from Nyaa are unaffected.
  - Added `title_strict_indexers` to `DEFAULTS` and the documented `CONFIG_TEMPLATE`.
  - Added 3 ranking tests (mismatch rejected, real match passes, gate scoped to configured indexers).
  - Verified live: `search tv "zzzznotarealshowzzz"` now exits 3; `search tv "Game of Thrones"` and `search movie "Inception"` exit 0.

Current Work:
Executing autonomous iteration.

Last Test Result:
PASSED

Current Problem:
The three end-to-end download smokes in TASK DoD (lines 233-236) require transferring real copyrighted media through a running transmission-daemon; not performed by the agent. Search, ranking, enqueue, import, and monitor paths are verified offline and with a stubbed RPC.

Next Action:
Human runs the E2E download smokes against a running transmission-daemon, then marks DoD 233-236 and sets Status: COMPLETE.

Last Updated:
2026-10-08T14:46:30.466121+00:00
