from arr.indexers.base import HttpClient, IndexerError, SchemaMismatchError
from arr.indexers.browser import BrowserSession
from arr.indexers.eztv import EztvAdapter
from arr.indexers.nyaa import NyaaAdapter
from arr.indexers.tpb import TpbAdapter
from arr.indexers.torrentio import TorrentioAdapter
from arr.indexers.yts import YtsAdapter

__all__ = [
    "BrowserSession",
    "EztvAdapter",
    "HttpClient",
    "IndexerError",
    "NyaaAdapter",
    "SchemaMismatchError",
    "TorrentioAdapter",
    "YtsAdapter",
    "build_adapters",
]


def build_adapters(cfg) -> list:
    http = HttpClient(cfg)
    enabled = cfg.get("enabled_indexers", []) or []
    adapters: list = []
    if "yts" in enabled:
        adapters.append(YtsAdapter(cfg.get("yts_base_url"), http))
    if "eztv" in enabled:
        adapters.append(EztvAdapter(cfg.get("eztv_base_url"), http))
    if "nyaa" in enabled:
        adapters.append(NyaaAdapter(cfg.get("nyaa_base_url"), http))
    if "tpb" in enabled:
        adapters.append(TpbAdapter(cfg.get("tpb_base_url"), http))
    if "torrentio" in enabled:
        adapters.append(TorrentioAdapter(cfg.get("torrentio_base_url"), http))
    return adapters
