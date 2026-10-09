from __future__ import annotations

import xml.etree.ElementTree as ET

from arr.core.models import MediaType, Query, Release
from arr.indexers.base import HttpClient, SchemaMismatchError

NYAA_NS = {"nyaa": "https://nyaa.si/xmlns/nyaa"}


class NyaaAdapter:
    name = "nyaa"

    def __init__(self, base_url: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def supports(self, media_type: MediaType) -> bool:
        return media_type == MediaType.TV

    async def search(self, q: Query) -> list[Release]:
        url = f"{self.base_url}/"
        resp = await self.http.get(
            url,
            key="nyaa",
            ttl_seconds=1800,
            params={"page": "rss", "q": q.text, "c": "1_2", "f": "0"},
        )
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as e:
            raise SchemaMismatchError(self.name, url, f"invalid RSS XML: {e}") from e
        out: list[Release] = []
        for item in root.iter("item"):
            try:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                seeders = item.findtext("nyaa:seeders", namespaces=NYAA_NS)
                leechers = item.findtext("nyaa:leechers", namespaces=NYAA_NS)
                size = item.findtext("nyaa:size", namespaces=NYAA_NS)
                raw_hash = (item.findtext("nyaa:infoHash", namespaces=NYAA_NS) or "").strip()
                if not title:
                    continue

                clean_hash = raw_hash.lower() if raw_hash else ""
                if link.startswith("magnet:"):
                    magnet = link
                    if not clean_hash:
                        clean_hash = _hash_from_magnet(magnet)
                elif clean_hash:
                    import urllib.parse

                    dn = urllib.parse.quote(title)
                    trackers = (
                        "&tr=http%3A%2F%2Fnyaa.tracker.wf%3A7777%2Fannounce"
                        "&tr=udp%3A%2F%2Fopen.stealth.si%3A80%2Fannounce"
                        "&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
                    )
                    magnet = f"magnet:?xt=urn:btih:{clean_hash}&dn={dn}{trackers}"
                elif link:
                    magnet = _magnet_from_link(link)
                    clean_hash = _hash_from_magnet(magnet)
                else:
                    continue

                if not clean_hash or clean_hash.startswith("http"):
                    continue


                out.append(
                    Release(
                        indexer=self.name,
                        title=title,
                        infohash=clean_hash,
                        magnet=magnet,
                        media_type=MediaType.TV,
                        seeds=_to_int(seeders) or 0,
                        peers=_to_int(leechers) or 0,
                        size_bytes=_parse_size(size),
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue
        return out



def _to_int(v) -> int | None:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _parse_size(v) -> int:
    if not v:
        return 0
    parts = str(v).replace(",", "").split()
    if len(parts) != 2:
        return 0
    try:
        value = float(parts[0])
    except ValueError:
        return 0
    unit = parts[1].lower()
    mult = {
        "b": 1,
        "kib": 1 << 10,
        "kb": 1 << 10,
        "mib": 1 << 20,
        "mb": 1 << 20,
        "gib": 1 << 30,
        "gb": 1 << 30,
        "tib": 1 << 40,
        "tb": 1 << 40,
    }
    return int(value * mult.get(unit, 0))


def _magnet_from_link(link: str) -> str:
    if link.startswith("magnet:"):
        return link
    return f"magnet:?xt=urn:btih:{link}"


def _hash_from_magnet(magnet: str) -> str:
    marker = "btih:"
    idx = magnet.lower().find(marker)
    if idx >= 0:
        return magnet[idx + len(marker) :].split("&")[0].lower()
    return magnet[:40].lower()
