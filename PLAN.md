# Implementation Plan

Status: NOT_STARTED

## Steps

1. Inspect the repository and existing architecture.
   - Confirm whether `pyproject.toml` and `uv.lock` exist; if not,
     plan `uv init --package` scaffolding.
   - Verify `uv` is installed: `uv --version`. If not, stop and report
     rather than falling back to `pip`.
   - Identify any existing CLI, config, or adapter code.
   - Record findings before writing code.

2. Scaffold the `uv`-managed Python package.
   - `pyproject.toml` with `[project]`, `[project.scripts]`
     (`arr = "arr.cli:app"`), and a `[dependency-groups] dev` group.
   - `uv lock` to produce `uv.lock`; commit it.
   - `src/arr/__init__.py`, `src/arr/cli.py` (typer app),
     `src/arr/__main__.py`.
   - `src/arr/config/` with TOML load (stdlib `tomllib`, `tomli`
     backport on 3.10), defaults, `config init`, validation, secret
     redaction.
   - `src/arr/log.py` with a leveled stderr logger that redacts
     secrets.
   - Exit codes as an `IntEnum` in `src/arr/exit.py`, wired through
     typer exceptions.
   - Subcommand stubs for `search`, `download`, `series`, `queue`,
     `status`, `cancel`, `import`, `daemon`, `config`, `version`.

3. Define core domain types (`src/arr/core/`).
   - Pydantic models: `Release`, `MediaType`, `Query`,
     `QualityProfile`, `DownloadRecord`, `SeedingPolicy`,
     `Episode`, `Season`, `Series`, `MonitoredSeries`,
     `SubtitleRecord`, `SubtitleSource`, `DownloadScope`.
   - `Adapter` protocol as specified in TASK R4 (async `search`).
   - Keep this module free of I/O so tests are trivial.

4. Implement release parsing and ranking (R5).
   - Wrap `guessit` behind `core.parse_release(title)`.
   - Hard-filter pass with config knobs, including season-pack
     awareness for whole-series scope.
   - Pure `rank(releases, profile, config) -> list[Scored]` with
     deterministic infohash tiebreak.
   - `--explain` rendering.
   - Fixture corpus covering movies, TV, season packs, anime, and
     malformed input. Tests assert stable ordering.

5. Implement the transmission wrapper (R2).
   - `src/arr/transmission/` with binary discovery, daemon start,
     health check, stop, RPC add/list/status/remove.
   - Windows probe: `PATH` then `%ProgramFiles%\Transmission\`.
   - Concurrency gate: a semaphore plus a `queued` state in SQLite;
     torrents are added stopped and started when a slot frees.
   - Distinct errors + exit code 4 for stale lock, port in use, auth
     failure, missing binary.
   - Test marked `@pytest.mark.integration` against a real daemon.

6. Implement indexer adapters (R4).
   - `src/arr/indexers/yts.py`, `eztv.py`, `nyaa.py`.
   - Shared `httpx.AsyncClient` with per-indexer min interval,
     exponential backoff with jitter on `429`/`503`, per-request
     timeout, configurable User-Agent, on-disk cache with TTL.
   - `respx` fixtures; tests run offline.
   - Schema-mismatch errors name adapter + URL.

7. Implement TMDB resolution (R3).
   - `src/arr/metadata/tmdb.py` with search-movie, search-tv,
     show → seasons → episodes, disk cache with per-type TTL (24h
     general, 6h for `Returning Series` episode lists), graceful
     degradation to free-text search.

8. Implement subtitle subsystem (R12).
   - `src/arr/subtitles/` with:
     - sibling/embedded detection during import
     - `.ass`/`.sub` → `.srt` conversion when `ffmpeg` is present,
       copy otherwise
     - OpenSubtitles REST client (`httpx`), API key auth, search by
       `imdb_id` + season + episode, deterministic candidate ranking
     - quota tracking and `quota_exceeded` state
     - filename generation `<basename>.<lang>.<ext>`
   - `subtitles` table writes on every decision, including `missing`.
   - Unit tests: candidate ranking, filename generation, extension
     handling with and without `ffmpeg`, quota exhaustion path.
   - `respx` fixtures for the OpenSubtitles API.

9. Implement series-level orchestration (R11).
   - `src/arr/series/` with:
     - `resolve_scope(show, season=None, episode=None, pack=False)`
       → list of target episodes or season packs
     - episode-level dedup against the `downloads`/`episodes` tables
     - season-pack coverage: an imported pack marks every episode in
       that season `imported`
     - enqueue respecting `max_concurrent_downloads`
   - `series add/list/remove/check` commands with a
     `monitored_series` table.
   - Initial whole-series download on `series add`.

10. Implement the monitor loop (R11).
    - `src/arr/monitor/` with a tick function that is idempotent and
      safe to interrupt.
    - On each tick: refresh TMDB, select aired-but-missing episodes
      within `monitor_lookahead_days`, exclude `imported`/`downloading`,
      search → rank → enqueue, import completed, apply seeding policy.
    - Per-indexer failure isolation: mark affected episodes
      `retry_pending`, continue the loop.
    - `arr daemon` wraps the tick with `monitor_poll_interval_minutes`
      and clean SIGINT/SIGTERM handling.
    - Unit tests with a frozen clock and fixture TMDB responses:
      assert an episode airs, gets enqueued on the next tick, and is
      not enqueued again on the tick after.

11. Wire `search` end to end.
    - TMDB resolve → adapter fan-out with `asyncio.gather` +
      `asyncio.timeout` → parse → filter → rank → rich table or
      `--json`.
    - Exit `3` on empty results. Isolate per-adapter failures.

12. Implement the download state machine (R6).
    - SQLite schema: `downloads` (infohash PK, media_type, tmdb_id,
      title, season, episode, indexer, state, timestamps, paths),
      `episodes` (tmdb_id, season, episode, state, infohash, path),
      `events` (append-only), `monitored_series`, `subtitles`.
    - Infohash dedupe with `--force`; episode dedupe with `--force`.
    - Queued → added → downloading → completed → imported → subtitled
      (or `failed`/`skipped`).

13. Implement import and library layout (R7).
    - `src/arr/importer/` with destination path computation, content
      enumeration and junk filtering, hardlink with `errno.EXDEV`
      fallback to copy, collision handling, season-pack distribution,
      subtitle sibling handling with language-suffix renaming.
    - Enforce the exact `downloads/movies` and `downloads/tv-shows`
      structure with `.incomplete/` staging.
    - Idempotent re-import.
    - Integration test with `tmp_path` and a fake payload covering
      media + sibling subtitle + missing subtitle cases.

14. Implement seeding policy (R8).
    - `ratio`, `time`, `manual`, `remove_on_import`.
    - Refuse `remove_on_import` + hardlink with a clear error.
    - Print the trade-off notice once per run.
    - Evaluate on `queue` and on a `daemon` tick.

15. Wire `download`, `queue`, `status`, `cancel`, `import`.
    - `download movie` path: search → select (`--pick`/`--auto`) →
      add → poll → import → subtitles → report.
    - `download tv` path: scope confirmation → series orchestration →
      queue → import → subtitles → report.
    - Idempotency check on every mutating command.

16. Implement `run.bat` and `run.sh` (R13).
    - `run.bat`:
      - `where uv` check; if missing, print the PowerShell install
        command and `pause` + exit non-zero.
      - `uv sync` in the repo root.
      - `uv run arr %*` (or `uv run arr --help` when no args).
      - On non-zero exit, print the code and `pause`.
    - `run.sh` mirrors the logic.
    - Manual test matrix: clean checkout with no `.venv`, with args,
      with no args, with `uv` missing (simulated by PATH scrub), and
      with a forced error to confirm `pause`.

17. Robustness pass against TASK R9.
    - Grep for hardcoded indexer domains; all must come from config.
    - Grep the whole repo for `pip `, `pip3 `, `python -m venv`,
      `poetry`, `pipenv`, `conda`; none allowed outside historical
      notes.
    - Verify timeouts on every `httpx` call and on the fan-out.
    - Verify secrets are redacted in logs and `--json`.
    - Verify daemon failure modes produce exit code 4 with hints.

18. Documentation.
    - `README.md`: install via `uv`, `run.bat` usage,
      `config init`, first-run walkthrough, command reference with
      whole-series vs episode examples, monitor walkthrough,
      subtitle setup (OpenSubtitles key).
    - `LEGAL.md`: client-only posture, user responsibility, no
      telemetry, no bundled indexers.
    - `GOTCHAS.md`: EZTV domain rotation, Nyaa RSS field gaps,
      cross-device hardlink fallback, anime absolute numbering,
      OpenSubtitles quota, `ffmpeg` absent, monitor tick idempotency
      edge cases.

19. Run the full test suite and linters via `uv`.
    - `uv run pytest` (offline), `uv run ruff check .`,
      `uv run mypy arr`.
    - `uv run pytest -m integration` against a local
      transmission-daemon.

20. Diagnose and fix failures.
    - Fix root causes, not symptoms. Re-run the failing test in
      isolation before the full suite.

21. Review the implementation against every TASK requirement and
    every Gotcha.
    - Walk R1–R13 and the Gotcha list item by item; note gaps.

22. Verify every Definition of Done item, including the three
    end-to-end smoke tests via `run.bat` and the no-duplication
    re-runs.

## Notes

Scope warning: R11 (monitoring) and R12 (subtitles) are each
comparable in size to the entire v1 search/rank/download/import
pipeline. Do not attempt them in the same iteration as the base
pipeline; land R1–R9 first, verify the movie smoke test, then add
R11, then R12, then R13.

Gotcha → handling map (verify each in step 21):

- EZTV domain churn → config-driven base URL; schema-mismatch error
  names adapter + URL.
- YTS API stability → config-driven; cache responses.
- Nyaa Cloudflare / rate limits → min interval, backoff with jitter,
  User-Agent, on-disk cache. No challenge bypass.
- Nyaa RSS missing fields → per-field HTML scrape fallback only.
- Cross-device hardlink failure → `errno.EXDEV` detection, copy
  fallback, `move` only when explicitly configured.
- Multi-file / season-pack torrents → per-episode distribution into
  `Season NN`; pack coverage marks all episodes imported.
- Sample/extras/junk files → filtered during content enumeration.
- Subtitle siblings → renamed to `<basename>.<lang>.<ext>`.
- `.ass`/`.sub` without `ffmpeg` → copied with original extension,
  language suffix still applied.
- Missing subtitles → media still imported; `missing` recorded in
  `subtitles` table.
- OpenSubtitles quota exhaustion → `quota_exceeded` state, retried on
  next daemon tick; import is not blocked.
- Destination collisions → size+infohash match = skip; else suffix;
  `--overwrite` replaces.
- Seeding after import → hardlink keeps data for seeding; trade-off
  printed once per run; `remove_on_import` + hardlink rejected.
- Sonarr/Radarr naming → templates fixed and covered by unit tests.
- transmission-daemon lifecycle → stale lock, port in use, auth
  failure each mapped to exit code 4 with hints; Windows install path
  probed explicitly.
- Duplicate downloads → infohash dedupe + episode dedupe in SQLite,
  `--force` override.
- Monitor tick re-enqueue → episode-level dedupe plus an
  `episodes.state` check; covered by a frozen-clock unit test.
- Indexer down during a tick → `retry_pending`, loop continues.
- Anime absolute numbering → preserved with a warning; remapping
  explicitly out of scope for v1.
- Secrets in logs → redaction in logger and `config show`.
- `run.bat` idempotency → `uv sync` is a no-op when current; no
  manual sentinel file needed.
- `uv` missing on a fresh machine → `run.bat` prints the install
  command and exits with a readable message.

Update this plan whenever implementation discoveries materially change
the approach. If a requirement turns out to be infeasible as written,
record the deviation here before changing TASK.md.