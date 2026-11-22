from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any

from guessit import guessit

from arr.core.models import MediaType, QualityProfile, Query, Release

BAD_SOURCES = ("cam", "ts", "hdts", "tc", "r5", "sample", "password")

SOURCE_ALIASES = {
    "bluray": "BluRay",
    "blu-ray": "BluRay",
    "bdrip": "BluRay",
    "brrip": "BluRay",
    "web-dl": "WEB-DL",
    "webdl": "WEB-DL",
    "web": "WEB-DL",
    "webrip": "WEBRip",
    "web-rip": "WEBRip",
    "hdtv": "HDTV",
    "tv": "HDTV",
}

CODEC_ALIASES = {
    "h.265": "HEVC",
    "h265": "HEVC",
    "hevc": "HEVC",
    "x265": "HEVC",
    "h.264": "AVC",
    "h264": "AVC",
    "x264": "AVC",
    "avc": "AVC",
    "av1": "AV1",
    "xvid": "XviD",
    "divx": "DivX",
}


def _norm_source(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if not raw:
            return None
    key = str(raw).lower().replace(" ", "").replace("_", "-")
    return SOURCE_ALIASES.get(key, str(raw))


def _norm_codec(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if not raw:
            return None
    key = str(raw).lower().replace(" ", "")
    return CODEC_ALIASES.get(key, str(raw))


def _norm_resolution(raw: Any) -> str | None:
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    s = str(raw).lower().replace("p", "").replace("i", "")
    if s in ("2160", "4320"):
        return f"{s}p"
    if s in ("1920", "1080"):
        return "1080p"
    if s == "720":
        return "720p"
    if s in ("576", "480", "bret"):
        return "480p"
    return f"{s}p" if s.isdigit() else str(raw)


def parse_release(title: str) -> dict[str, Any]:
    g = guessit(title)
    out: dict[str, Any] = {
        "title": g.get("title"),
        "year": g.get("year"),
        "season": g.get("season") if isinstance(g.get("season"), int) else None,
        "episode": g.get("episode") if isinstance(g.get("episode"), int) else None,
        "resolution": _norm_resolution(g.get("screen_size")),
        "source": _norm_source(g.get("source")),
        "codec": _norm_codec(g.get("video_codec")),
        "group": g.get("release_group"),
        "is_pack": (
            isinstance(g.get("season"), list)
            or bool(g.get("episode_list"))
            or (
                g.get("type") in ("episode", "episode_list")
                and g.get("season") is not None
                and g.get("episode") is None
            )
            or ("complete" in str(g.get("other") or "").lower())
        ),
        "is_proper": bool(g.get("proper")),
        "is_repack": bool(g.get("repack")),
    }
    return out


def enrich_release(r: Release) -> Release:
    p = parse_release(r.title)
    r.title = p["title"] if p["title"] else r.title
    r.year = r.year or p["year"]
    r.season = r.season if r.season is not None else p["season"]
    r.episode = r.episode if r.episode is not None else p["episode"]
    r.resolution = p["resolution"] or r.resolution
    r.source = p["source"] or r.source
    r.codec = p["codec"] or r.codec
    r.group = p["group"] or r.group
    r.is_pack = r.is_pack or p["is_pack"]
    r.is_proper = r.is_proper or p["is_proper"]
    r.is_repack = r.is_repack or p["is_repack"]
    return r


def _is_bad(r: Release) -> bool:
    hay = " ".join(filter(None, [r.title, r.source, r.resolution, r.group])).lower()
    return any(b in hay for b in BAD_SOURCES)


@dataclass
class Scored:
    release: Release
    score: dict[str, Any] = field(default_factory=dict)
    rejected: str | None = None


def _norm_tokens(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _title_relevant(r: Release, q: Query) -> bool:
    """Reject releases whose title does not plausibly match the query.

    Some indexers (notably EZTV) return their latest torrents when no entry
    matches, so a title check is required. Only applied to indexers listed in
    ``title_strict_indexers`` (default ``["eztv"]``) to avoid rejecting
    romanized anime titles from Nyaa.
    """
    wanted = _norm_tokens(q.title or q.text or "")
    if not wanted:
        return True
    have = _norm_tokens(r.title)
    if not have:
        return False
    if wanted in have:
        return True
    if difflib.SequenceMatcher(None, wanted, have).ratio() >= 0.6:
        return True
    ws, hs = set(wanted.split()), set(have.split())
    if ws and len(ws & hs) / len(ws) >= 0.8:
        return True
    return False


def hard_filter(r: Release, q: Query, profile: QualityProfile, cfg: dict) -> str | None:
    if _is_bad(r):
        return "bad source/quality (CAM/TS/TC/R5/sample/password)"
    strict = cfg.get("title_strict_indexers", ["eztv"]) or []
    if r.indexer in strict and not _title_relevant(r, q):
        return f"title {r.title!r} does not match {q.title or q.text!r}"
    min_seeders = int(cfg.get("min_seeders", profile.min_seeders))
    if r.seeds < min_seeders:
        return f"seeders {r.seeds} < {min_seeders}"
    allowed = cfg.get("resolutions") or profile.resolutions
    if r.resolution and allowed and r.resolution not in allowed:
        return f"resolution {r.resolution} not in allowlist"
    min_mb = cfg.get(f"min_size_mb_{q.media_type.value}", cfg.get("min_size_mb"))
    max_mb = cfg.get(f"max_size_mb_{q.media_type.value}", cfg.get("max_size_mb"))
    size_mb = r.size_bytes / (1024 * 1024) if r.size_bytes else 0
    if min_mb and size_mb and size_mb < float(min_mb):
        return f"size {size_mb:.0f}MB < {min_mb}MB"
    if max_mb and size_mb and size_mb > float(max_mb):
        return f"size {size_mb:.0f}MB > {max_mb}MB"
    if q.media_type == MediaType.TV and q.season is not None and not r.is_pack:
        if r.season is not None and r.season != q.season:
            return f"season {r.season} != {q.season}"
        if q.episode is not None and r.episode is not None and r.episode != q.episode:
            return f"episode {r.episode} != {q.episode}"
    if q.media_type == MediaType.MOVIE and q.imdb_id and r.imdb_id:
        if q.imdb_id.lower() != r.imdb_id.lower():
            return f"imdb_id {r.imdb_id} != {q.imdb_id}"
    if q.media_type == MediaType.MOVIE and q.year is not None and r.year is not None:
        if abs(r.year - q.year) > 1:
            return f"year {r.year} != {q.year}"
    return None


def score_release(r: Release, q: Query, profile: QualityProfile) -> dict[str, Any]:
    if r.resolution in profile.resolutions:
        res_rank = profile.resolutions.index(r.resolution)
    else:
        res_rank = len(profile.resolutions)
    src_order = profile.source_order
    src_rank = src_order.index(r.source) if r.source in src_order else len(src_order)
    codec_map = {"HEVC": "x265", "AVC": "x264"}
    codec_key = codec_map.get(r.codec or "", r.codec or "")
    if codec_key in profile.codecs:
        codec_rank = profile.codecs.index(codec_key)
    else:
        codec_rank = len(profile.codecs)
    return {
        "seeders": r.seeds,
        "resolution_rank": res_rank,
        "source_rank": src_rank,
        "codec_rank": codec_rank,
        "size_bytes": r.size_bytes,
        "infohash": r.infohash.lower(),
    }


def rank(
    releases: list[Release],
    q: Query,
    profile: QualityProfile | None = None,
    cfg: dict | None = None,
) -> list[Scored]:
    profile = profile or QualityProfile()
    cfg = cfg or {}
    out: list[Scored] = []
    for r in releases:
        enrich_release(r)
        reason = hard_filter(r, q, profile, cfg)
        if reason:
            out.append(Scored(release=r, rejected=reason))
            continue
        out.append(Scored(release=r, score=score_release(r, q, profile)))
    accepted = [s for s in out if s.rejected is None]
    rejected = [s for s in out if s.rejected is not None]
    priority_order = cfg.get("indexer_priority", []) or []
    accepted.sort(
        key=lambda s: (
            priority_order.index(s.release.indexer)
            if s.release.indexer in priority_order
            else len(priority_order),
            +s.score["seeders"] * -1,
            s.score["resolution_rank"],
            s.score["source_rank"],
            s.score["codec_rank"],
            s.score["size_bytes"] if s.score["size_bytes"] > 0 else 1 << 62,
            s.score["infohash"],
        )
    )
    return accepted + rejected


def explain(scored: list[Scored]) -> str:
    lines = []
    for s in scored:
        r = s.release
        if s.rejected:
            lines.append(f"REJECTED {r.title}: {s.rejected}")
        else:
            lines.append(
                f"{r.title}: seeders={s.score['seeders']} res_rank={s.score['resolution_rank']} "
                f"src_rank={s.score['source_rank']} codec_rank={s.score['codec_rank']} "
                f"size={s.score['size_bytes']} hash={s.score['infohash']}"
            )
    return "\n".join(lines)
