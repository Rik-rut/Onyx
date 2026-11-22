#!/usr/bin/env bash
set -e

PUID=${PUID:-1000}
PGID=${PGID:-1000}

# Create config directories if they do not exist
mkdir -p /config/transmission
mkdir -p /downloads/movies
mkdir -p /downloads/tv-shows
mkdir -p /downloads/incomplete

# Generate initial config.toml if missing
if [ ! -f /config/config.toml ]; then
  cat <<EOF > /config/config.toml
download_root = "/downloads"
library_root = "/downloads"
import_mode = "hardlink"
transmission_rpc_host = "127.0.0.1"
transmission_rpc_port = 9091
prefer_season_packs = true
seeding_policy = "ratio"
subtitles_enabled = true
subtitle_languages = ["en"]
max_concurrent_downloads = 3
torrentio_base_url = "http://torrentio-scraper:8080"
EOF
fi

# Start transmission-daemon in the background
echo "[ARR] Starting transmission-daemon..."
transmission-daemon \
  --config-dir /config/transmission \
  --download-dir /downloads \
  --incomplete-dir /downloads/incomplete \
  --peerport 51413 \
  --allowed "*.*.*.*" \
  --no-auth \
  --foreground=false

# Wait briefly for transmission-daemon to start listening
sleep 1

# Launch ARR Web Dashboard
echo "[ARR] Launching ARR Web Dashboard on 0.0.0.0:3698..."
exec uv run arr web --host 0.0.0.0 --port 3698 --config /config/config.toml
