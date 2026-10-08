from arr.indexers.base import HttpClient, IndexerError, SchemaMismatchError
from arr.indexers.eztv import EztvAdapter
from arr.indexers.nyaa import NyaaAdapter
from arr.indexers.yts import YtsAdapter

__all__ = [
    "EztvAdapter",
    "HttpClient",
    "IndexerError",
    "NyaaAdapter",
    "SchemaMismatchError",
    "YtsAdapter",
    "build_adapters",
]


def build_adapters(cfg) -> list:
    http = HttpClient(cfg)
    return [
        YtsAdapter(cfg.get("yts_base_url"), http),
        EztvAdapter(cfg.get("eztv_base_url"), http),
        NyaaAdapter(cfg.get("nyaa_base_url"), http),
    ]
