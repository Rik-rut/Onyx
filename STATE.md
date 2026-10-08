# Autonomous Agent State

Status: IN_PROGRESS

Iteration: 16

Current Objective:
Finish the no-API-key migration (TVMaze/IMDb/Subscene/YIFY), fix defects surfaced by live smoke testing, and make the full test/lint/type gate genuinely pass.

Completed:
- Migrated metadata layer: `src/arr/metadata/tvmaze.py` (TVMaze REST, disk cache, 6h episode TTL for Returning Series, stale-cache fallback) and `src/arr/metadata/imdb.py` (curl_cffi + selectolax scrape + suggestion fallback).
- Migrated subtitles: `src/arr/subtitles/base.py` (SubtitleCandidate/SubtitleError/rank_candidates), `subscene.py`, `yify.py`; rewrote `subtitles/service.py` (sibling → Subscene → YIFY → `missing`); added `SubtitleSource.SUBSCENE`/`YIFY`.
- Updated `config/settings.py` (removed all API keys; added `tvmaze_base_url`, `imdb_base_url`, `imdb_suggestion_base_url`, `subscene_base_url`, `yify_subtitles_base_url`), `models.py`, `pipeline.py`.
- Deleted obsolete `metadata/tmdb.py`, `subtitles/opensubtitles.py`, `tests/test_tmdb.py`.
- Fixed selectolax 1.0 API: `selectolax.parser` (Modest, deprecated) → `selectolax.lexbor.LexborHTMLParser`.
- Fixed real bugs found by live smoke tests:
  - EZTV endpoint path `api/get_torrents` → `api/get-torrents` (underscore returned HTTP 404 HTML).
  - YTS default mirror `yts.mx` (dead DNS) → `yts.lt`.
  - YIFY multi-selector `tr, li, .subtitle-row` returned duplicate nodes → dedupe by link.
  - IMDb HTML search is bot-blocked (HTTP 202) → added public suggestion-endpoint fallback.
  - R1 bug: `--config` passed a `str` to `init_config`/`load_config` → coerced to `Path`.
  - R5 `--explain` was implemented but not reachable → exposed on `search movie`/`search tv`.
  - Ruff `extend-exclude = [..., "arr"]` accidentally excluded the `src/arr` package, so the main package was never linted. Fixed to `"/arr"` (the root mypy junction) and corrected all 55 newly-visible lint errors (E501/E501/F841).
- Added tests: `test_tvmaze.py`, `test_scrapers.py` (imdb/subscene/yify), `test_config.py`; rewrote `test_subtitles.py`.
- Updated README/GOTCHAS/LEGAL/TASK.md for the no-API-key architecture; PLAN.md marked COMPLETE.
- Verified live: movie search returns YTS releases; TV search returns ranked EZTV releases with `--explain`; TVMaze resolves imdb ids; transmission-daemon start → RPC handshake → stop; `config init/show` + redaction; `--json`.
- Gates: `uv run pytest` 71 passed, 1 deselected; `uv run ruff check .` clean (main package now included); `uv run mypy arr` clean.

Current Work:
Iteration complete. Remaining DoD items are the three live end-to-end download smoke tests.

Last Test Result:
PASSED

Current Problem:
TASK DoD lines 233-236 (end-to-end download smokes) require transferring real copyrighted media through a running transmission-daemon; not performed by the agent. All component paths (metadata resolve, indexer search/rank/explain, RPC add handshake, import + subtitle placement) are verified via live checks and the offline `tmp_path` integration tests.

Next Action:
Human runs the E2E download smokes (`run.bat download movie "Inception" --auto`, `run.bat download tv "<airing show>"`, `run.bat series add ...` + `daemon`) against a running transmission-daemon; then mark DoD lines 233-236 and set Status: COMPLETE.

Last Updated:
2026-10-08T14:37:01.696580+00:00
