from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


SECRET_KEYS = ("transmission_rpc_pass", "subdl_api_key")

DEFAULTS: dict = {
    "download_root": "downloads",
    "library_root": "downloads",
    "transmission_rpc_host": "127.0.0.1",
    "transmission_rpc_port": 9091,
    "transmission_rpc_user": "",
    "transmission_rpc_pass": "",
    "transmission_download_dir": "downloads",
    "transmission_remote": "",
    "yts_base_url": "https://yts.lt",
    "eztv_base_url": "https://eztv.re",
    "nyaa_base_url": "https://nyaa.si",
    "tvmaze_base_url": "https://api.tvmaze.com",
    "tvmaze_catalog_pages": 4,
    "imdb_base_url": "https://www.imdb.com",
    "imdb_suggestion_base_url": "https://v3.sg.media-imdb.com/suggestion",
    "subscene_base_url": "https://subscene.com",
    "yify_subtitles_base_url": "https://yifysubtitles.ch",
    "addic7ed_base_url": "https://www.addic7ed.com",
    "opensubtitles_base_url": "https://rest.opensubtitles.org",
    "subdl_base_url": "https://api.subdl.com",
    "subdl_api_key": "",
    "quality_profile": "default",
    "seeding_policy": "remove_on_import",
    "seed_ratio": 1.0,
    "seed_time_hours": 24.0,
    "user_agent": "arr/0.1 (+https://localhost)",
    "subtitle_languages": ["en"],
    "subtitles_enabled": True,
    "subtitles_forced_only": False,
    "max_concurrent_downloads": 3,
    "prefer_season_packs": True,
    "monitor_poll_interval_minutes": 30,
    "monitor_lookahead_days": 7,
    "unmonitor_ended_series": False,
    "import_mode": "move",
    "min_seeders": 1,
    "min_size_mb_movie": 200,
    "max_size_mb_movie": 80000,
    "min_size_mb_tv": 100,
    "max_size_mb_tv": 80000,
    "resolutions": ["2160p", "1080p", "720p"],
    "cache_ttl_hours": 24,
    "episode_cache_ttl_hours": 6,
    "request_interval_seconds": {"yts": 1.0, "eztv": 1.0, "nyaa": 2.0},
    "title_strict_indexers": ["eztv"],
    "max_download_speed_kbps": 0,
    "max_upload_speed_kbps": 0,
}

CONFIG_TEMPLATE = """\
# arr configuration
# Secrets are never logged or printed unless --show-secrets is passed.

# Metadata / subtitle source base URLs (free or scraped; no API keys)
tvmaze_base_url = "https://api.tvmaze.com"
# TVMaze show-index pages cached locally (250 shows each) for Discover rankings
tvmaze_catalog_pages = 4
imdb_base_url = "https://www.imdb.com"
# IMDb suggestion JSON endpoint (fallback when the HTML search is bot-blocked)
imdb_suggestion_base_url = "https://v3.sg.media-imdb.com/suggestion"
subscene_base_url = "https://subscene.com"
yify_subtitles_base_url = "https://yifysubtitles.ch"

download_root = "downloads"
library_root = "downloads"

transmission_rpc_host = "127.0.0.1"
transmission_rpc_port = 9091
transmission_rpc_user = ""
transmission_rpc_pass = ""
transmission_download_dir = "downloads"
# Optional explicit path to the transmission-remote binary
transmission_remote = ""

# Indexer base URLs (config-driven; rotate as needed)
yts_base_url = "https://yts.lt"
eztv_base_url = "https://eztv.re"
nyaa_base_url = "https://nyaa.si"

quality_profile = "default"
seeding_policy = "remove_on_import"   # ratio | time | manual | remove_on_import
seed_ratio = 1.0
seed_time_hours = 24.0
import_mode = "move"   # hardlink | copy | move

user_agent = "arr/0.1"
min_seeders = 1

# Quality / size filters (per media type, megabytes)
resolutions = ["2160p", "1080p", "720p"]
min_size_mb_movie = 200
max_size_mb_movie = 80000
min_size_mb_tv = 100
max_size_mb_tv = 80000

# Response caching and per-indexer request spacing (seconds)
cache_ttl_hours = 24
episode_cache_ttl_hours = 6
request_interval_seconds = { yts = 1.0, eztv = 1.0, nyaa = 2.0 }

subtitle_languages = ["en"]
subtitles_enabled = true
subtitles_forced_only = false
# Subtitle providers
addic7ed_base_url = "https://www.addic7ed.com"
opensubtitles_base_url = "https://rest.opensubtitles.org"
subdl_base_url = "https://api.subdl.com"
subdl_api_key = ""

max_concurrent_downloads = 3
prefer_season_packs = true

monitor_poll_interval_minutes = 30
monitor_lookahead_days = 7
unmonitor_ended_series = false

# Indexers whose search results are title-validated (they may return
# unrelated latest torrents when a query does not match).
title_strict_indexers = ["eztv"]

# Bandwidth speed limits (KB/s, 0 = unlimited)
max_download_speed_kbps = 0
max_upload_speed_kbps = 0
"""


class Config(BaseModel):
    values: dict = Field(default_factory=lambda: dict(DEFAULTS))

    def get(self, key: str, default=None):
        return self.values.get(key, DEFAULTS.get(key, default))

    def __getitem__(self, key: str):
        return self.get(key)

    def redacted(self) -> dict:
        out = dict(self.values)
        for k in SECRET_KEYS:
            if out.get(k):
                out[k] = "***redacted***"
        return out


def default_config_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "arr" / "config.toml"
        return Path.home() / "AppData" / "Roaming" / "arr" / "config.toml"
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "arr" / "config.toml"
    return Path.home() / ".config" / "arr" / "config.toml"


def load_config(path: Path | str | None = None) -> Config:
    if path is not None:
        p = Path(path)
    else:
        local = Path.cwd() / "config.toml"
        p = local if local.exists() else default_config_path()
    values = dict(DEFAULTS)
    if p.exists():
        with p.open("rb") as f:
            user = tomllib.load(f)
        values.update(user)
    return Config(values=values)


def init_config(path: Path | str | None = None) -> Path:
    p = Path(path) if path is not None else default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return p


def save_config(cfg: Config, path: Path | str | None = None) -> Path:
    """Save Config back to TOML file, preserving valid TOML syntax."""
    p = Path(path) if path is not None else default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# Generated by ARR interactive settings editor\n\n"]
    for k, v in sorted(cfg.values.items()):
        if isinstance(v, bool):
            lines.append(f"{k} = {'true' if v else 'false'}\n")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}\n")
        elif isinstance(v, str):
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k} = "{escaped}"\n')
        elif isinstance(v, list):
            items = []
            for item in v:
                if isinstance(item, str):
                    esc = item.replace("\\", "\\\\").replace('"', '\\"')
                    items.append(f'"{esc}"')
                elif isinstance(item, bool):
                    items.append("true" if item else "false")
                else:
                    items.append(str(item))
            lines.append(f"{k} = [{', '.join(items)}]\n")
        elif isinstance(v, dict):
            dict_items = []
            for dk, dv in v.items():
                if isinstance(dv, (int, float)):
                    dict_items.append(f"{dk} = {dv}")
                elif isinstance(dv, str):
                    dict_items.append(f'{dk} = "{dv}"')
                else:
                    dict_items.append(f"{dk} = {dv}")
            lines.append(f"{k} = {{ {', '.join(dict_items)} }}\n")
    p.write_text("".join(lines), encoding="utf-8")
    return p
