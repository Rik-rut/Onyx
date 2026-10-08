from __future__ import annotations

import os
import sys
from pathlib import Path

from pydantic import BaseModel, Field

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]


SECRET_KEYS = ("tmdb_api_key", "opensubtitles_api_key", "transmission_rpc_pass")

DEFAULTS: dict = {
    "tmdb_api_key": "",
    "opensubtitles_api_key": "",
    "download_root": "downloads",
    "library_root": "downloads",
    "transmission_rpc_host": "127.0.0.1",
    "transmission_rpc_port": 9091,
    "transmission_rpc_user": "",
    "transmission_rpc_pass": "",
    "transmission_download_dir": "downloads",
    "transmission_remote": "",
    "yts_base_url": "https://yts.mx",
    "eztv_base_url": "https://eztv.re",
    "nyaa_base_url": "https://nyaa.si",
    "quality_profile": "default",
    "seeding_policy": "ratio",
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
    "import_mode": "hardlink",
    "min_seeders": 1,
    "min_size_mb_movie": 200,
    "max_size_mb_movie": 80000,
    "min_size_mb_tv": 100,
    "max_size_mb_tv": 80000,
    "resolutions": ["2160p", "1080p", "720p"],
    "cache_ttl_hours": 24,
    "episode_cache_ttl_hours": 6,
    "request_interval_seconds": {"yts": 1.0, "eztv": 1.0, "nyaa": 2.0},
}

CONFIG_TEMPLATE = """\
# arr configuration
# Secrets are never logged or printed unless --show-secrets is passed.

tmdb_api_key = ""
opensubtitles_api_key = ""

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
yts_base_url = "https://yts.mx"
eztv_base_url = "https://eztv.re"
nyaa_base_url = "https://nyaa.si"

quality_profile = "default"
seeding_policy = "ratio"   # ratio | time | manual | remove_on_import
seed_ratio = 1.0
seed_time_hours = 24.0
import_mode = "hardlink"   # hardlink | copy | move

user_agent = "arr/0.1"
min_seeders = 1

subtitle_languages = ["en"]
subtitles_enabled = true
subtitles_forced_only = false

max_concurrent_downloads = 3
prefer_season_packs = true

monitor_poll_interval_minutes = 30
monitor_lookahead_days = 7
unmonitor_ended_series = false
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


def load_config(path: Path | None = None) -> Config:
    p = path or default_config_path()
    values = dict(DEFAULTS)
    if p.exists():
        with p.open("rb") as f:
            user = tomllib.load(f)
        values.update(user)
    return Config(values=values)


def init_config(path: Path | None = None) -> Path:
    p = path or default_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        p.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return p
