# Gotchas

- **EZTV domain churn** — the base URL is config-driven (`eztv_base_url`). A schema-mismatch error
  names the adapter and URL so you know to rotate it.
- **YTS stability** — responses are cached on disk; a schema change raises
  `SchemaMismatchError` naming `yts` + the URL. A successful query with no matches omits the
  `movies` key; that is treated as zero results, not a schema error.
- **YTS base-URL migration** — YTS announced a move to `https://movies-api.accel.li/api/v2/`
  (sunset 2026-04-10). The default `yts_base_url` is `https://yts.lt`; rotate it in config when the
  old host stops serving. No code change is required since the base URL is config-driven.
- **Nyaa rate limits / Cloudflare** — per-indexer min interval (`nyaa`: 2s), backoff with jitter on
  429/503, configurable User-Agent, on-disk TTL cache. `arr` does **not** solve challenges.
- **Nyaa RSS gaps** — seeders/leechers/size/infoHash are parsed from the `nyaa:` namespace; missing
  fields are tolerated (0 / magnet-derived hash) rather than failing the whole row.
- **Cross-device hardlinks** — importing across volumes raises `EXDEV`; `arr` falls back to copy, then
  move only when `import_mode = "move"`.
- **Season packs** — a chosen pack marks every episode in its season `imported` without per-episode
  torrents; episodes covered by an imported pack are skipped on later ticks.
- **Junk / samples** — `Sample/`, `Extras/`, `*.nfo`, `*.txt`, `*.url`, `.DS_Store`, `thumbs.db` are
  ignored when picking the primary media file.
- **Sibling subtitles** — renamed to `<basename>.<lang>.<ext>`; `.ass`/`.sub` become `.srt` only when
  `ffmpeg` is present, otherwise copied with their original extension.
- **Missing subtitles** — the media file still imports; the `subtitles` table records `missing`.
- **IMDb/Subscene/YIFY scraping** — all three are scraped with `curl_cffi` browser impersonation. An
  HTML-structure change or block raises a source-specific error; metadata degrades to free-text indexer
  search and subtitles fall through to the next source (Subscene → YIFY → `missing`). The import itself
  is never blocked by a scrape failure.
- **Subtitle scrape rate limit / block** — records `error` on the subtitle row and retries on the next
  daemon tick.
- **TVMaze rate limit (429)** — exponential backoff with jitter; a stale cache entry is preferred over a
  hard failure.
- **Destination collisions** — same size + partial hash → skip; otherwise `.1`/`.2` suffix;
  `--overwrite` replaces.
- **Hardlink + remove_on_import** — refused: it would delete the library's only copy. Hardlink imports
  keep seeding data in `.incomplete/` on purpose; the trade-off is printed once per run.
- **Naming** — Sonarr/Radarr conventions are covered by unit tests; keep templates stable when adding
  indexers.
- **transmission-daemon lifecycle** — stale lock, port-in-use, and RPC auth failures map to exit code 4
  with a remediation hint; on Windows the binary is also probed under `%ProgramFiles%\Transmission`.
- **Duplicate downloads** — infohash dedupe in `downloads` plus episode-level dedupe in `episodes`;
  re-running any command is a no-op unless `--force`.
- **Monitor tick re-enqueue** — prevented by episode-level `state` checks; covered by a frozen-clock
  unit test. An indexer down mid-tick marks episodes `retry_pending` and is retried next tick.
- **Anime absolute numbering** — preserved with a warning; remapping is out of scope for v1.
- **Secrets** — the Transmission RPC password is redacted in logs and `config show` unless
  `--show-secrets`. No API keys exist (all metadata/subtitle sources are free or scraped).
- **`run.bat` idempotency** — `uv sync` is a no-op when the lockfile/env are current; no sentinel file.
- **`run.bat` / `run.sh` working directory** — both `cd` to their own directory first, so launching from
  Explorer, a shortcut, or any other cwd still finds `pyproject.toml` (otherwise `uv sync` fails with
  "No `pyproject.toml` found").
- **`run.bat` when `uv` isn't on PATH (Explorer double-click)** — GUI launches can inherit a stale PATH.
  The launcher probes `%USERPROFILE%\.local\bin`, `.cargo\bin`, `%APPDATA%\uv`, `%LOCALAPPDATA%\Programs\uv`,
  and scoop shims before reporting uv missing.
- **`run.bat` double-click window closing** — with no arguments it runs `arr --help` and always `pause`s,
  so the output stays readable. Terminal runs with arguments still honor the real exit code.
- **`uv` missing on a clean machine** — `run.bat` prints the install command and exits non-zero with a
  `pause`.
