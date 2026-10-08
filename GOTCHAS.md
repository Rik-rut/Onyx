# Gotchas

- **EZTV domain churn** — the base URL is config-driven (`eztv_base_url`). A schema-mismatch error
  names the adapter and URL so you know to rotate it.
- **YTS stability** — responses are cached on disk; a schema change raises
  `SchemaMismatchError` naming `yts` + the URL.
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
- **OpenSubtitles quota** — exhaustion records `quota_exceeded` and retries on the next daemon tick;
  the import itself is not blocked.
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
- **Secrets** — TMDB/OpenSubtitles keys and RPC password are redacted in logs and `config show`
  unless `--show-secrets`.
- **`run.bat` idempotency** — `uv sync` is a no-op when the lockfile/env are current; no sentinel file.
- **`uv` missing on a clean machine** — `run.bat` prints the install command and exits non-zero with a
  `pause`.
