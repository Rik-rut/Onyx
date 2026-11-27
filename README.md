# Onyx

Onyx helps you find and download movies and TV shows from public torrent
indexers, then puts them in a tidy folder layout that Plex, Jellyfin and
similar media servers can read. No accounts, no API keys, no cloud service —
it runs entirely on your own machine.

It ships with a web dashboard (the easiest way to use it), an interactive
console app, and a plain command-line tool.

## What it does

- **Searches** movies, TV shows and anime across public indexers (YTS, EZTV,
  Nyaa, animetosho, The Pirate Bay and a Torrentio sidecar).
- **Ranks** the results by seeders and quality so you can pick the best one
  in seconds.
- **Downloads** the chosen release via a local Transmission daemon (the
  actual download engine — Onyx never stores your data itself).
- **Imports** finished downloads into a clean folder layout named in the
  Sonarr/Radarr style, so Plex/Jellyfin recognise the files without manual
  matching.
- **Adds English subtitles** next to each movie/episode by default.
- **Monitors** TV shows you care about and downloads new episodes as they
  air (optional).
- **Seeds** downloads for a configurable time/ratio before removing them,
  or keeps them until you tell it to stop.

## Quick start (web dashboard — recommended)

Requirements:

- [uv](https://docs.astral.sh/uv/) — the Python/tool manager (one install,
  no other Python setup)
- Transmission (the download daemon) — install from
  [transmission-torrent.com](https://transmission-torrent.com/) and make sure
  `transmission-daemon` is available on your PATH
- Optional: ffmpeg, for converting `.ass`/`.sub` subtitles to `.srt`

Then:

```bat
:: Windows
run.bat web
```

```sh
# Linux/macOS
./run.sh web
```

The dashboard opens in your browser automatically — and if Transmission isn't already running, Onyx starts it for you. If it doesn't open, go to **http://localhost:3698**. The first time you log in you will use the default credentials `admin` / `1234` — the app will ask you to change them immediately, and it will not let you use the dashboard until you have.

From there:

1. **Discover** — browse what's popular right now, or use **Search** to look
   for a specific movie or show.
2. Pick a release and hit download.
3. Watch progress in **Queue**.
4. Once the download finishes, it appears in **Library**, named and foldered
   for your media server.

## Using the console

If you prefer the terminal, double-click `run.bat` (or `./run.sh`) with no
arguments to launch the interactive console — it walks you through search,
download and monitoring from a menu.

The plain command-line tool is also available:

```sh
arr search movie "Inception"
arr download movie "Inception" --auto
arr series add "Breaking Bad"
arr daemon          # background monitor loop for TV shows
```

Run `arr --help` for the full list.

## How it works

```
search  →  pick a release  →  Transmission downloads it  →  Onyx imports it
                                                          →  library folder + subtitles
```

- **Search** — public indexers are queried and results ranked by seeders/quality.
- **Download** — the release is handed to the local Transmission daemon; Onyx
  tracks progress and lets you cancel.
- **Import** — when the download completes, the file is moved/linked into
  `downloads/movies/` or `downloads/tv-shows/` under a
  `<Title> (<Year>)` / `<Show> (<Year>)/Season NN/` layout. English subtitles
  are fetched automatically and named so your media server picks them up.
- **Monitor** (optional) — for shows you add, the daemon checks for new
  episodes on a schedule, downloads and imports them automatically.

## Library layout

```
downloads/
  movies/<Title> (<Year>)/<Title> (<Year>).<ext>
                                     <Title> (<Year>).en.srt
  tv-shows/<Show> (<Year>)/Season NN/<Show> - S01E01 - <Episode Title>.<ext>
                                                       <...>.en.srt
```

Files in `.incomplete/` subfolders are never treated as library. If two files
with the same name exist, identical ones are skipped and different ones get a
`.1` / `.2` suffix.

## Configuration

`arr config init` writes a documented template; `arr config show` prints the
effective settings (secrets are redacted). The file lives at
`%APPDATA%\arr\config.toml` (Windows) or `~/.config/arr/config.toml`
(Linux/macOS) — override with `--config <path>`.

Nothing needs to be configured to get started. The important settings are
`download_root`, `library_root`, and the Transmission connection
(`transmission_rpc_*`). Everything else has sensible defaults.

## Running on a server (ZimaOS)

`docker-compose.yml` carries a `x-casaos` block so ZimaOS can import it
directly: Settings → App Store → *Import from compose file* → select
`docker-compose.yml`. The app appears as **Onyx Media Discovery &
Downloader**, exposing the web dashboard on port 3698 plus the Transmission
ports (9091, 51413 tcp/udp). The `id` and `icon` fields are placeholders until
the repository is published — point them at the public repo, then re-import.

## Troubleshooting

- **Dashboard won't open / port busy** — something else is already using port
  3698; find it with `netstat -ano | grep :3698` and stop it, or change the
  port.
- **No results for a search** — the indexers are public and may be slow or
  temporarily unreachable; try again, and check that Torrentio (if used) is
  running.
- **Downloads never start** — the web UI starts Transmission automatically, so if nothing downloads, make sure Transmission is installed and the daemon is reachable on `127.0.0.1:9091` (or the port in your config).
- **Old anime episodes missing** — Nyaa only returns its ~30 most recent
  uploads, so very old episodes can legitimately not appear.

## Developers

```sh
uv sync
uv run pytest
uv run ruff check .
uv run mypy arr
```

Frontend (the web dashboard) lives in `frontend/`:

```sh
cd frontend && npm install && npm run build
```

The compiled SPA is written to `src/arr/web/static/dist/` (gitignored).

## License

MIT — see [LICENSE](LICENSE).
