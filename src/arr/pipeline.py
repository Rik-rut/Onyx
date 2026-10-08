from __future__ import annotations

__all__ = [
    "search",
    "download_movie",
    "download_tv",
    "series_add",
    "series_list",
    "series_remove",
    "series_check",
    "list_queue",
    "get_status",
    "cancel_download",
    "import_download",
    "run_daemon",
]


async def search(media_type, query, cfg, season=None, episode=None):
    raise NotImplementedError


async def download_movie(query, cfg, **kwargs):
    raise NotImplementedError


async def download_tv(query, cfg, **kwargs):
    raise NotImplementedError


async def series_add(query, cfg):
    raise NotImplementedError


def series_list(cfg):
    raise NotImplementedError


def series_remove(series_id, cfg, delete_files=False):
    raise NotImplementedError


async def series_check(series_id, cfg):
    raise NotImplementedError


def list_queue(cfg):
    raise NotImplementedError


def get_status(download_id, cfg):
    raise NotImplementedError


async def cancel_download(download_id, cfg, delete_data=False):
    raise NotImplementedError


async def import_download(download_id, cfg, overwrite=False):
    raise NotImplementedError


async def run_daemon(cfg):
    raise NotImplementedError
