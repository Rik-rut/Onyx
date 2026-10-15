from __future__ import annotations

import asyncio
import re
import shutil
import sys
import time
from pathlib import Path

from arr.config.settings import Config
from arr.core.models import Episode, MediaType, QualityProfile, Query, Release, Series
from arr.core.parsing import Scored, explain, rank
from arr.db import DB
from arr.importer.layout import (
    delete_path,
    find_episode_file,
    import_episode,
    import_movie,
    media_files,
    prune_boundary,
    prune_empty_dirs,
    subtitle_files_adjacent,
)
from arr.indexers import build_adapters
from arr.log import get_logger
from arr.metadata.imdb import ImdbClient, ImdbError
from arr.metadata.imdb import degrade as degrade_movie
from arr.metadata.tvmaze import TvmazeClient, TvmazeError
from arr.metadata.tvmaze import degrade as degrade_tv
from arr.monitor.loop import select_airing, tick
from arr.series.orchestration import (
    group_by_season,
    mark_pack_imported,
    pick_season_pack,
    resolve_scope,
)
from arr.subtitles.service import ensure_subtitles
from arr.transmission.errors import DependencyUnavailable
from arr.transmission.process import (
    RpcClient,
    active_count,
    ensure_daemon,
    is_active_torrent,
    is_complete_torrent,
    plan_slots,
)

logger = get_logger("pipeline")

DB_PATH = Path(".cache") / "arr" / "arr.db"


def _db(cfg: Config) -> DB:
    if cfg.get("db_path"):
        return DB(Path(str(cfg.get("db_path"))))
    root = Path(str(cfg.get("library_root", "downloads"))).parent
    path = root / ".cache" / "arr" / "arr.db"
    return DB(path)


def _rpc(cfg: Config) -> RpcClient:
    try:
        ensure_daemon(cfg)
    except DependencyUnavailable:
        pass
    return RpcClient(
        str(cfg.get("transmission_rpc_host", "127.0.0.1")),
        int(cfg.get("transmission_rpc_port", 9091)),
        str(cfg.get("transmission_rpc_user", "") or ""),
        str(cfg.get("transmission_rpc_pass", "") or ""),
    )



def check_disk_space(target_path: Path, required_bytes: int) -> tuple[bool, int, int]:
    """Check free space on target_path volume. Returns (has_space, free_bytes, required_bytes)."""
    p = target_path if target_path.exists() else target_path.parent
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        stat = shutil.disk_usage(str(p))
        free = stat.free
        return (free >= required_bytes, free, required_bytes)
    except OSError:
        return (True, 0, required_bytes)


def _library_root(cfg: Config) -> Path:
    return Path(str(cfg.get("library_root", "downloads"))).resolve()


def _staging_dir(cfg: Config, media_type: str) -> Path:
    sub = "movies" if media_type == "movie" else "tv-shows"
    d = Path(str(cfg.get("download_root", "downloads"))).resolve() / sub
    d.mkdir(parents=True, exist_ok=True)
    return d



def _torrent_content_path(torrent: dict | None) -> Path | None:
    """Best-effort path to a completed torrent's payload."""
    if not torrent:
        return None
    base = torrent.get("downloadDir")
    name = torrent.get("name")
    if base and name:
        return Path(str(base)) / str(name)
    if base:
        return Path(str(base))
    return None


def _import_mode(cfg: Config) -> str:
    return str(cfg.get("import_mode", "hardlink"))


def _print_hardlink_notice(cfg: Config, count: int = 1) -> None:
    if _import_mode(cfg) == "hardlink":
        notice = (
            "Note: importing via hardlink keeps torrent data in place so seeding "
            "can continue (the library shares the same blocks)."
        )
        suffix = f" ({count} torrents)" if count > 1 else ""
        print(notice + suffix)

__all__ = [
    "search",
    "search_candidates",
    "enqueue_release",
    "download_movie",
    "download_tv",
    "series_add",
    "series_list",
    "series_remove",
    "series_check",
    "list_queue",
    "get_status",
    "cancel_download",
    "remove_download_and_files",
    "match_torrent",
    "pause_download",
    "resume_download",
    "set_download_priority",
    "download_magnet",
    "apply_speed_limits",
    "import_download",
    "run_daemon",
    "_import_record",
    "_enqueue_episodes",
    "_enqueue_series_query",
    "_poll_and_import",
]


async def search_candidates(
    media_type: MediaType,
    query: str,
    cfg: Config,
    season: int | None = None,
    episode: int | None = None,
    *,
    year: int | None = None,
    imdb_id: str | None = None,
    tmdb_id: int | None = None,
    title: str | None = None,
) -> tuple[list[Release], list[Scored], Query]:
    q = Query(
        media_type=media_type,
        text=title or query,
        season=season,
        episode=episode,
        year=year,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
        title=title or query,
    )
    # Metadata resolve (best effort) only if not already supplied
    try:
        if media_type == MediaType.MOVIE:
            if not q.imdb_id and not q.year:
                imdb = ImdbClient(cfg)
                m = imdb.search_movie(query)
                if m:
                    q.imdb_id = m.get("imdb_id") or m.get("id")
                    q.title = m.get("title")
                    q.year = m.get("year")
        else:
            if not q.tmdb_id and not q.imdb_id:
                tvm = TvmazeClient(cfg)
                s = tvm.search_tv(query)
                if s:
                    q.tmdb_id = s.get("id")
                    q.title = s.get("name")
                    ext = s.get("externals") or {}
                    q.imdb_id = ext.get("imdb")
    except (TvmazeError, ImdbError) as e:
        if media_type == MediaType.MOVIE:
            degrade_movie(query)
        else:
            degrade_tv(query)
        print(f"warning: metadata lookup failed: {e}", file=sys.stderr)

    q.text = q.title or query

    releases = await _fan_out(q, cfg)
    profile = QualityProfile(
        resolutions=list(cfg.get("resolutions") or ["2160p", "1080p", "720p"]),
        min_seeders=int(cfg.get("min_seeders", 1)),
    )
    scored = rank(releases, q, profile, cfg.values)
    accepted = [s.release for s in scored if s.rejected is None]
    return accepted, scored, q


async def search(
    media_type: MediaType,
    query: str,
    cfg: Config,
    season: int | None = None,
    episode: int | None = None,
    explain_mode: bool = False,
    *,
    year: int | None = None,
    imdb_id: str | None = None,
    tmdb_id: int | None = None,
    title: str | None = None,
) -> list[Release]:
    accepted, scored, _ = await search_candidates(
        media_type,
        query,
        cfg,
        season=season,
        episode=episode,
        year=year,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
        title=title,
    )
    if explain_mode:
        print(explain(scored), file=sys.stderr)
    return accepted


def _pick(results: list[Release], auto: bool, pick: int | None) -> Release | None:
    if not results:
        return None
    if auto:
        return results[0]
    if pick is not None and 0 <= pick < len(results):
        return results[pick]
    for i, r in enumerate(results[:20]):
        print(f"[{i}] {r.title} — seeds={r.seeds} size={r.size_bytes/1e9:.1f}GB")
    try:
        idx = int(input("pick #: ").strip())
    except (ValueError, EOFError):
        return None
    return results[idx] if 0 <= idx < len(results) else None


async def download_movie(
    query, cfg, *, pick=None, auto=False, yes=False, no_wait=False, force=False
):
    releases = await search(MediaType.MOVIE, query, cfg)
    if not releases:
        print("No results.", file=sys.stderr)
        raise SystemExit(3)
    chosen = _pick(releases, auto, pick)
    if chosen is None:
        print("No selection.", file=sys.stderr)
        raise SystemExit(2)
    print(f"Selected: {chosen.title}")
    if not yes:
        if input("Start download? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return
    db = _db(cfg)
    existing = db.get_download(chosen.infohash)
    if existing and existing.get("state") not in ("skipped", "failed") and not force:
        print(f"Already known (state={existing['state']}); use --force to re-add.")
        db.close()
    staging = _staging_dir(cfg, "movie")
    if getattr(chosen, "size_bytes", 0) > 0:
        has_space, free_b, req_b = check_disk_space(staging, chosen.size_bytes)
        if not has_space:
            gb_free = free_b / (1024**3)
            gb_req = req_b / (1024**3)
            print(
                f"warning: target disk space low ({gb_free:.1f} GB free, {gb_req:.1f} GB required)",
                file=sys.stderr,
            )
    rpc = _rpc(cfg)
    limit = int(cfg.get("max_concurrent_downloads", 3))
    paused = False
    try:
        active = active_count(await rpc.list_torrents())
        paused = plan_slots(active, limit, 1)[0]
    except DependencyUnavailable as e:
        print(str(e), file=sys.stderr)
        db.close()
        raise SystemExit(4)
    except Exception:
        paused = False
    try:
        await rpc.add_magnet(chosen.magnet, str(staging), paused=paused)
    except DependencyUnavailable as e:
        print(str(e), file=sys.stderr)
        db.close()
        raise SystemExit(4)
    new_state = "queued" if paused else "added"
    if existing:
        db.set_download_state(
            chosen.infohash,
            new_state,
            media_type="movie",
            tmdb_id=chosen.tmdb_id,
            imdb_id=chosen.imdb_id,
            title=chosen.title,
            year=chosen.year,
            indexer=chosen.indexer,
            download_dir=str(staging),
            content_path=None,
            destination_path=None,
        )
    else:
        db.add_download(
            chosen.infohash,
            media_type="movie",
            tmdb_id=chosen.tmdb_id,
            imdb_id=chosen.imdb_id,
            title=chosen.title,
            year=chosen.year,
            indexer=chosen.indexer,
            download_dir=str(staging),
            state=new_state,
        )
    if paused:
        print("Queued (max_concurrent_downloads reached).")
    if no_wait:
        print("Added (no-wait).")
        db.close()
        return
    _promote_queued(cfg, db)
    # poll until completed (bounded), then import
    deadline = time.time() + 3600
    while time.time() < deadline:
        try:
            t = await rpc.get(chosen.infohash)
        except DependencyUnavailable:
            break
        if t and is_complete_torrent(t):
            content = _torrent_content_path(t)
            db.set_download_state(
                chosen.infohash, "completed",
                content_path=str(content) if content else None,
            )
            break
        await asyncio.sleep(5)
    rec = db.get_download(chosen.infohash)
    if rec:
        final = _import_record(rec, cfg, db)
        if final:
            print(f"Imported to {final}")
    _print_hardlink_notice(cfg)
    db.close()


async def download_tv(
    query,
    cfg,
    *,
    season=None,
    episode=None,
    pack=False,
    pick=None,
    auto=False,
    yes=False,
    no_wait=False,
    force=False,
):
    if season is None and episode is None:
        scope = "entire series"
    elif episode is None:
        scope = f"S{season}"
    else:
        scope = f"S{season}E{episode}"
    print(f"Scope: {scope}")
    if not yes:
        if input("Start download? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return

    db = _db(cfg)
    prefer_packs = pack or bool(cfg.get("prefer_season_packs", True))
    try:
        if season is None and episode is None:
            n = await _enqueue_series_query(query, cfg, db, force=force, prefer_packs=prefer_packs)
        else:
            n = await _enqueue_tv_scope(
                query, cfg, db, season=season, episode=episode, force=force,
                prefer_packs=prefer_packs,
            )
    finally:
        db.close()
    if n == 0:
        print("Nothing new to download.", file=sys.stderr)
        raise SystemExit(3)
    _print_hardlink_notice(cfg, n)


async def _resolve_series(query: str, cfg: Config) -> Series | None:
    try:
        tvm = TvmazeClient(cfg)
        s = tvm.search_tv(query)
        if not s:
            return None
        return tvm.full_series(s["id"])
    except TvmazeError as e:
        print(f"warning: TVMaze resolve failed: {e}", file=sys.stderr)
        return None


async def _enqueue_series_query(query, cfg, db, *, force=False, prefer_packs=None) -> int:
    """Whole-series: resolve via TVMaze, enumerate missing episodes, enqueue."""
    series = await _resolve_series(query, cfg)
    if series is None:
        print(
            f"warning: could not resolve series {query!r}; falling back to single search",
            file=sys.stderr,
        )
        return await _enqueue_tv_scope_by_search(
            query, cfg, db, season=None, episode=None, force=force
        )
    return await _enqueue_episodes(
        series, resolve_scope(series), cfg, db, force=force, prefer_packs=prefer_packs
    )


async def _enqueue_tv_scope(
    query, cfg, db, *, season, episode, force=False, prefer_packs=None
) -> int:
    series = await _resolve_series(query, cfg)
    if series is None:
        return await _enqueue_tv_scope_by_search(
            query, cfg, db, season=season, episode=episode, force=force
        )
    return await _enqueue_episodes(
        series, resolve_scope(series, season, episode), cfg, db,
        force=force, prefer_packs=prefer_packs,
    )


async def _enqueue_tv_scope_by_search(query, cfg, db, *, season, episode, force=False) -> int:
    """Fallback when TVMaze is unavailable: search indexers and enqueue the top release."""
    releases = await search(MediaType.TV, query, cfg, season=season, episode=episode)
    if not releases:
        return 0
    chosen = releases[0]
    existing = db.get_download(chosen.infohash)
    if existing and existing.get("state") not in ("skipped", "failed") and not force:
        return 0
    staging = _staging_dir(cfg, "tv")
    try:
        await _rpc(cfg).add_magnet(chosen.magnet, str(staging))
    except DependencyUnavailable as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(4)
    if existing:
        db.set_download_state(
            chosen.infohash,
            "added",
            media_type="tv",
            title=chosen.title,
            season=season,
            episode=episode,
            indexer=chosen.indexer,
            download_dir=str(staging),
            content_path=None,
            destination_path=None,
        )
    else:
        db.add_download(
            chosen.infohash,
            media_type="tv",
            title=chosen.title,
            season=season,
            episode=episode,
            indexer=chosen.indexer,
            download_dir=str(staging),
            state="added",
        )
    return 1


async def _enqueue_episodes(
    series: Series,
    episodes: list[Episode],
    cfg,
    db,
    *,
    force=False,
    prefer_packs: bool | None = None,
) -> int:
    """Search + rank missing episodes; enqueue the best release for each.

    `episodes` is the caller-chosen scope (whole series, a season, or one
    episode). Episodes already queued/downloaded/imported are skipped unless
    ``force`` is set, which keeps whole-series and monitor runs idempotent.

    When ``prefer_packs`` is true (default from ``prefer_season_packs``), a
    season whose missing episodes could be covered by an accepted season pack
    enqueues the single pack instead of one torrent per episode. A pack marks
    every episode in its season as covered.
    """
    if not episodes:
        return 0
    if force:
        needed = list(episodes)
    else:
        needed = [
            e
            for e in episodes
            if db.episode_state(series.tmdb_id, e.season_number, e.episode_number)
            not in ("imported", "downloading", "queued", "added", "completed")
        ]
    if not needed:
        return 0
    if prefer_packs is None:
        prefer_packs = bool(cfg.get("prefer_season_packs", True))
    profile = QualityProfile(
        resolutions=list(cfg.get("resolutions") or ["2160p", "1080p", "720p"]),
        min_seeders=int(cfg.get("min_seeders", 1)),
    )
    staging = _staging_dir(cfg, "tv")
    limit = int(cfg.get("max_concurrent_downloads", 3))

    # Phase 1: decide the best release per missing episode, preferring packs.
    plans: list[tuple[list[Episode], Release]] = []
    seen_hashes: set[str] = set()
    for season, season_eps in group_by_season(needed).items():
        pack: Release | None = None
        per_episode: list[tuple[Episode, Release]] = []
        for ep in season_eps:
            q = Query(
                media_type=MediaType.TV,
                text=series.title,
                title=series.title,
                imdb_id=series.imdb_id,
                season=ep.season_number,
                episode=ep.episode_number,
            )
            releases = await _fan_out(q, cfg)
            scored = rank(releases, q, profile, cfg.values)
            accepted = [s.release for s in scored if s.rejected is None]
            if accepted:
                if prefer_packs:
                    chosen = accepted[0]
                else:
                    # prefer a per-episode release over a pack covering the season
                    chosen = next((r for r in accepted if not r.is_pack), accepted[0])
                per_episode.append((ep, chosen))
                if pack is None and prefer_packs:
                    pack = pick_season_pack(accepted)
        if pack is not None:
            covered = [ep for ep, _ in per_episode]
            ex_pack = db.get_download(pack.infohash)
            if pack.infohash in seen_hashes or (
                ex_pack and ex_pack.get("state") not in ("skipped", "failed")
            ):
                for ep in season_eps:
                    db.set_episode_state(
                        series.tmdb_id, ep.season_number, ep.episode_number, "imported",
                        infohash=pack.infohash,
                    )
                continue
            seen_hashes.add(pack.infohash)
            plans.append((covered if covered else list(season_eps), pack))
            continue
        for ep, chosen in per_episode:
            ex_chosen = db.get_download(chosen.infohash)
            if chosen.infohash in seen_hashes or (
                ex_chosen and ex_chosen.get("state") not in ("skipped", "failed")
            ):
                db.set_episode_state(
                    series.tmdb_id, ep.season_number, ep.episode_number, "imported",
                    infohash=chosen.infohash,
                )
                continue
            seen_hashes.add(chosen.infohash)
            plans.append(([ep], chosen))

    if not plans:
        return 0

    # Phase 2: add respecting max_concurrent_downloads. Queued -> paused=True.
    rpc = _rpc(cfg)
    active = 0
    try:
        active = active_count(await rpc.list_torrents())
    except Exception:
        active = 0
    paused_flags = plan_slots(active, limit, len(plans))

    count = 0
    for (covered, chosen), paused in zip(plans, paused_flags):
        if getattr(chosen, "size_bytes", 0) > 0:
            has_space, free_b, req_b = check_disk_space(staging, chosen.size_bytes)
            if not has_space:
                gb_free = free_b / (1024**3)
                gb_req = req_b / (1024**3)
                print(
                    f"warning: disk space low ({gb_free:.1f} GB free, {gb_req:.1f} GB needed)",
                    file=sys.stderr,
                )
        try:
            await rpc.add_magnet(chosen.magnet, str(staging), paused=paused)
        except DependencyUnavailable as e:
            print(str(e), file=sys.stderr)
            raise SystemExit(4)
        lead = covered[0]
        new_state = "queued" if paused else "added"
        existing_dl = db.get_download(chosen.infohash)
        if existing_dl:
            db.set_download_state(
                chosen.infohash,
                new_state,
                media_type="tv",
                tmdb_id=series.tmdb_id,
                title=series.title,
                season=lead.season_number,
                episode=lead.episode_number if len(covered) == 1 else None,
                episode_title=lead.name if len(covered) == 1 else None,
                imdb_id=series.imdb_id,
                year=series.year,
                indexer=chosen.indexer,
                download_dir=str(staging),
                content_path=None,
                destination_path=None,
            )
        else:
            db.add_download(
                chosen.infohash,
                media_type="tv",
                tmdb_id=series.tmdb_id,
                title=series.title,
                season=lead.season_number,
                episode=lead.episode_number if len(covered) == 1 else None,
                episode_title=lead.name if len(covered) == 1 else None,
                imdb_id=series.imdb_id,
                year=series.year,
                indexer=chosen.indexer,
                download_dir=str(staging),
                state=new_state,
            )
        for ep in covered:
            db.set_episode_state(
                series.tmdb_id, ep.season_number, ep.episode_number, new_state,
                infohash=chosen.infohash,
            )
        count += 1
    await _promote_queued(cfg, db)
    return count


async def _promote_queued(cfg: Config, db: DB) -> None:
    """Start queued (paused) torrents while a free slot exists (best effort)."""
    limit = int(cfg.get("max_concurrent_downloads", 3))
    try:
        rpc = _rpc(cfg)
    except Exception:
        return
    try:
        torrents = await rpc.list_torrents()
    except Exception:
        return
    by_hash = {str(t.get("hashString", "")).lower(): t for t in torrents}
    active = active_count(torrents)
    if active >= limit:
        return
    for rec in db.list_downloads():
        if active >= limit:
            break
        if rec.get("state") != "queued":
            continue
        t = by_hash.get(str(rec["infohash"]).lower())
        if not t:
            continue
        try:
            await rpc.start(t["id"])
        except Exception:
            continue
        db.set_download_state(rec["infohash"], "downloading")
        if rec.get("season") is not None and rec.get("episode") is not None:
            db.set_episode_state(
                int(rec.get("tmdb_id") or 0),
                int(rec["season"]),
                int(rec["episode"]),
                "downloading",
            )
        active += 1


async def enqueue_release(
    chosen: Release,
    cfg: Config,
    *,
    media_type: str = "movie",
    season: int | None = None,
    episode: int | None = None,
    tmdb_id: int | None = None,
    imdb_id: str | None = None,
    year: int | None = None,
    force: bool = False,
) -> tuple[bool, str]:
    """Enqueue a single release into Transmission and the local database.

    Respects max_concurrent_downloads: if all slots are full, adds paused (queued).
    Returns (success, message).
    """
    db = _db(cfg)
    try:
        existing = db.get_download(chosen.infohash)
        if existing and existing.get("state") not in ("skipped", "failed") and not force:
            return False, f"Already known (state={existing['state']}); use --force to re-add."
        staging = _staging_dir(cfg, media_type)
        rpc = _rpc(cfg)
        await apply_speed_limits(rpc, cfg)
        limit = int(cfg.get("max_concurrent_downloads", 3))
        paused = False
        try:
            torrents = await rpc.list_torrents()
            active = active_count(torrents)
            paused = plan_slots(active, limit, 1)[0]
        except DependencyUnavailable as e:
            return False, f"Transmission unavailable: {e}"
        except Exception:
            paused = False

        if getattr(chosen, "size_bytes", 0) > 0:
            has_space, free_b, req_b = check_disk_space(staging, chosen.size_bytes)
            if not has_space:
                gb_free = free_b / (1024**3)
                gb_req = req_b / (1024**3)
                print(
                    f"warning: disk space low ({gb_free:.1f} GB free, {gb_req:.1f} GB needed)",
                    file=sys.stderr,
                )

        try:
            await rpc.add_magnet(chosen.magnet, str(staging), paused=paused)
        except DependencyUnavailable as e:
            return False, f"Transmission unavailable: {e}"
        except Exception as e:
            return False, f"Failed to add magnet: {e}"

        new_state = "queued" if paused else "added"
        resolved_year = year if year is not None else chosen.year
        if existing:
            db.set_download_state(
                chosen.infohash,
                new_state,
                media_type=media_type,
                tmdb_id=tmdb_id or chosen.tmdb_id,
                imdb_id=imdb_id or chosen.imdb_id,
                title=chosen.title,
                year=resolved_year,
                season=season if season is not None else chosen.season,
                episode=episode if episode is not None else chosen.episode,
                indexer=chosen.indexer,
                download_dir=str(staging),
                content_path=None,
                destination_path=None,
            )
        else:
            db.add_download(
                chosen.infohash,
                media_type=media_type,
                tmdb_id=tmdb_id or chosen.tmdb_id,
                imdb_id=imdb_id or chosen.imdb_id,
                title=chosen.title,
                year=resolved_year,
                season=season if season is not None else chosen.season,
                episode=episode if episode is not None else chosen.episode,
                indexer=chosen.indexer,
                download_dir=str(staging),
                state=new_state,
            )
        tid = tmdb_id if tmdb_id is not None else chosen.tmdb_id
        if (
            media_type == "tv"
            and tid is not None
            and season is not None
            and episode is not None
        ):
            db.set_episode_state(
                int(tid),
                int(season),
                int(episode),
                new_state,
                infohash=chosen.infohash,
            )
        if not paused:
            try:
                await _promote_queued(cfg, db)
            except Exception:
                pass
        msg = "Queued (download limit reached)" if paused else "Started downloading"
        logger.info(
            f"Enqueued {media_type}: '{chosen.title}' "
            f"[{chosen.infohash[:8]}...] -> {new_state} ({msg})"
        )
        return True, msg
    finally:
        db.close()


async def _fan_out(q: Query, cfg: Config) -> list[Release]:
    adapters = [a for a in build_adapters(cfg) if a.supports(q.media_type)]

    async def _one(a):
        try:
            return await asyncio.wait_for(a.search(q), timeout=30.0)
        except Exception as e:
            print(f"warning: indexer {a.name} failed: {e}", file=sys.stderr)
            return []

    groups = await asyncio.gather(*[_one(a) for a in adapters])
    out: list[Release] = []
    for g in groups:
        out.extend(g)
    return out


async def series_add(query, cfg):
    try:
        tvm = TvmazeClient(cfg)
        s = tvm.search_tv(query)
        if not s:
            print("No series found.", file=sys.stderr)
            raise SystemExit(3)
        series = tvm.full_series(s["id"])
    except TvmazeError as e:
        print(f"TVMaze error: {e}", file=sys.stderr)
        raise SystemExit(4)
    db = _db(cfg)
    sid = db.add_monitored(series.tmdb_id, series.title, series.imdb_id, series.status, None)
    print(f"Added monitored series: {series.title} ({series.status}) id={sid}")
    # R11: initial whole-series download
    try:
        n = await _enqueue_episodes(series, resolve_scope(series), cfg, db)
        if n:
            print(f"Queued {n} episode torrent(s) for {series.title}")
            _print_hardlink_notice(cfg, n)
    except SystemExit:
        raise
    finally:
        db.close()


def series_list(cfg):
    db = _db(cfg)
    rows = db.list_monitored()
    out = []
    for r in rows:
        eps = db.episodes_for_series(int(r["tmdb_id"]))
        imported = sum(1 for e in eps if e["state"] == "imported")
        downloading = sum(1 for e in eps if e["state"] in ("queued", "added", "downloading"))
        out.append(
            {
                "id": r["id"],
                "title": r["title"],
                "status": r["status"],
                "last_checked_at": r["last_checked_at"],
                "imported_episodes": imported,
                "pending_episodes": downloading,
                "missing_episodes": len(eps) - imported - downloading,
            }
        )
    db.close()
    return out


def series_remove(series_id, cfg, delete_files=False):
    db = _db(cfg)
    rows = [r for r in db.list_monitored() if int(r["id"]) == int(series_id)]
    if not rows:
        db.close()
        print("No such series.", file=sys.stderr)
        raise SystemExit(3)
    series = rows[0]
    if delete_files:
        removed = _delete_series_files(series, cfg, db)
        print(f"Deleted {removed} file(s) for {series['title']}")
    db.remove_monitored(int(series_id))
    db.close()
    print(f"Removed monitored series {series_id}")


def _delete_series_files(series: dict, cfg: Config, db: DB) -> int:
    from arr.importer.layout import sanitize_name

    root = _library_root(cfg) / "tv-shows"
    title = sanitize_name(str(series["title"]))
    candidates = [root / title]
    if root.exists():
        candidates.extend(
            p for p in root.iterdir() if p.is_dir() and p.name.startswith(f"{title} (")
        )
    removed = 0
    for target in candidates:
        if not target.exists():
            continue
        for p in sorted(target.rglob("*"), reverse=True):
            try:
                if p.is_file():
                    p.unlink()
                    removed += 1
                elif p.is_dir():
                    p.rmdir()
            except OSError:
                continue
        try:
            target.rmdir()
        except OSError:
            pass
    return removed


def _resolve_content(rec: dict, cfg: Config | None = None) -> Path | None:
    """Path to import from, or None if it can't be determined safely.

    Prefers the per-torrent `content_path` recorded from the daemon. Falls back
    to Transmission RPC query, title subdirectory, or fuzzy token match in
    `download_dir` when safe.
    """
    cp = rec.get("content_path")
    if cp:
        p_cp = Path(str(cp))
        if p_cp.exists():
            return p_cp

    # Try resolving via Transmission RPC if available and infohash is present
    if cfg is not None and rec.get("infohash"):
        try:
            rpc = _rpc(cfg)
            torrents = asyncio.run(rpc.list_torrents())
            target_t = next(
                (
                    t
                    for t in torrents
                    if str(t.get("hashString", "")).lower() == str(rec["infohash"]).lower()
                ),
                None,
            )
            if target_t:
                t_name = target_t.get("name")
                t_dir = target_t.get("downloadDir") or rec.get("download_dir")
                if t_dir and t_name:
                    cand = Path(str(t_dir)) / t_name
                    if cand.exists():
                        return cand
        except Exception:
            pass

    dd = rec.get("download_dir")
    if not dd:
        return None
    p = Path(str(dd))
    if p.name in (".incomplete", "movies", "tv-shows"):
        title = rec.get("title")
        if title:
            candidate = p / title
            if candidate.exists():
                return candidate
            if p.exists() and p.is_dir():
                clean_title = re.sub(r"[^\w\s]", " ", title.lower())
                tokens = [
                    tok
                    for tok in clean_title.split()
                    if len(tok) > 2
                    and tok
                    not in (
                        "the",
                        "and",
                        "1080p",
                        "720p",
                        "bluray",
                        "webrip",
                        "x264",
                        "x265",
                        "hevc",
                    )
                ]
                for entry in p.iterdir():
                    e_name = entry.name.lower()
                    if tokens and all(t in e_name for t in tokens[:3]):
                        return entry
        return None
    return p if p.exists() else None


def _mirror_subtitles_to_content(content: Path, final_path: Path) -> None:
    """Mirror any subtitles generated next to final_path into the content directory."""
    if not final_path.exists():
        return
    final_dir = final_path.parent
    sub_files = list(final_dir.glob(f"{final_path.stem}.*.srt")) + list(
        final_dir.glob(f"{final_path.stem}.srt")
    )
    if not sub_files:
        return

    # Find the primary video file in content
    if content.is_file():
        target_video = content
    elif content.is_dir():
        files = media_files(content)
        if not files:
            return
        target_video = max(files, key=lambda p: p.stat().st_size)
    else:
        return

    target_dir = target_video.parent
    target_base = target_video.stem

    for sub in sub_files:
        suffix_parts = sub.name[len(final_path.stem):]
        if not suffix_parts.startswith("."):
            suffix_parts = f".{suffix_parts}"
        dest_sub = target_dir / f"{target_base}{suffix_parts}"
        if dest_sub != sub and not dest_sub.exists():
            try:
                shutil.copy2(str(sub), str(dest_sub))
                logger.info(f"Mirrored subtitle to torrent content directory: {dest_sub.name}")
            except Exception as e:
                logger.debug(f"Could not mirror subtitle to {dest_sub}: {e}")


def _import_record(rec: dict, cfg: Config, db: DB, *, overwrite: bool = False) -> Path | None:
    """Import one completed download's content into the library. Idempotent."""
    content = _resolve_content(rec, cfg=cfg)
    if content is None or not content.exists():
        return None
    media_type = rec.get("media_type")
    mode = _import_mode(cfg)
    library = _library_root(cfg)

    if media_type == "movie":
        logger.info(f"Importing movie: '{rec.get('title')}' from {content}")
        final = import_movie(
            content,
            library,
            rec.get("title") or "Unknown",
            rec.get("year"),
            mode=mode,
            overwrite=overwrite,
        )
        if final:
            logger.info(f"Successfully imported movie: '{rec.get('title')}' -> {final}")
            db.set_download_state(rec["infohash"], "imported", destination_path=str(final))
            ensure_subtitles(
                final,
                cfg=cfg,
                db=db,
                imdb_id=rec.get("imdb_id"),
                tmdb_id=rec.get("tmdb_id"),
                release_name=rec.get("title") or "",
            )
            _mirror_subtitles_to_content(content, final)
        return final

    # TV: single episode or season pack
    season = rec.get("season")
    episode = rec.get("episode")
    if season is None:
        return None
    series = Series(
        tmdb_id=int(rec.get("tmdb_id") or 0),
        title=rec.get("title") or "Unknown",
        year=rec.get("year"),
        imdb_id=rec.get("imdb_id"),
    )
    if episode is not None:
        if content.is_dir():
            primary = find_episode_file(content, int(season), int(episode))
        else:
            primary = content
        if primary is None:
            files = media_files(content) if content.is_dir() else [content]
            primary = max(files, key=lambda p: p.stat().st_size) if files else None
        if primary is None:
            return None
        logger.info(
            f"Importing TV episode: '{series.title}' "
            f"S{int(season):02d}E{int(episode):02d} from {primary}"
        )
        final = import_episode(
            primary, library, series, int(season), int(episode),
            rec.get("episode_title") or "", mode=mode, overwrite=overwrite,
        )
        if final:
            logger.info(
                f"Successfully imported TV episode: '{series.title}' "
                f"S{int(season):02d}E{int(episode):02d} -> {final}"
            )
            db.set_episode_state(
                series.tmdb_id, int(season), int(episode), "imported", path=str(final)
            )
            ensure_subtitles(
                final, cfg=cfg, db=db, imdb_id=series.imdb_id, tmdb_id=series.tmdb_id,
                season=int(season), episode=int(episode), release_name=rec.get("title") or "",
            )
            _mirror_subtitles_to_content(primary, final)
            db.set_download_state(rec["infohash"], "imported", destination_path=str(final))
        return final

    return _import_season_pack(content, cfg, db, rec, series, int(season), mode, overwrite)


def _import_season_pack(
    content: Path,
    cfg: Config,
    db: DB,
    rec: dict,
    series: Series,
    season: int,
    mode: str,
    overwrite: bool,
) -> Path | None:
    """Import each episode in a season pack into its own Season NN directory."""
    from arr.core.parsing import parse_release

    files = media_files(content) if content.is_dir() else [content]
    if not files:
        return None
    last: Path | None = None
    imported = 0
    for f in files:
        parsed = parse_release(f.name)
        ep = parsed.get("episode")
        if ep is None:
            continue
        final = import_episode(
            f, _library_root(cfg), series, season, int(ep),
            "", mode=mode, overwrite=overwrite,
        )
        if final:
            last = final
            imported += 1
            db.set_episode_state(series.tmdb_id, season, int(ep), "imported", path=str(final))
            ensure_subtitles(
                final, cfg=cfg, db=db, imdb_id=series.imdb_id, tmdb_id=series.tmdb_id,
                season=season, episode=int(ep), release_name=rec.get("title") or "",
            )
            _mirror_subtitles_to_content(f, final)
    if imported:
        mark_pack_imported(db, series, season)
        db.set_download_state(rec["infohash"], "imported", destination_path=str(last))
    return last


async def series_check(series_id, cfg):
    db = _db(cfg)
    rows = [r for r in db.list_monitored() if int(r["id"]) == int(series_id)]
    if not rows:
        print("No such series.", file=sys.stderr)
        db.close()
        raise SystemExit(3)
    row = rows[0]
    try:
        series = TvmazeClient(cfg).full_series(int(row["tmdb_id"]))
    except TvmazeError as e:
        print(f"TVMaze error: {e}", file=sys.stderr)
        db.close()
        raise SystemExit(4)
    wanted = select_airing(
        series, db, lookahead_days=int(cfg.get("monitor_lookahead_days", 7))
    )
    if not wanted:
        print(f"No episodes due for {series.title}.")
        db.close()
        return
    try:
        n = await _enqueue_episodes(series, wanted, cfg, db)
    finally:
        db.close()
    print(f"{n} episode torrent(s) queued for {series.title} ({len(wanted)} due).")


def list_queue(cfg):
    db = _db(cfg)
    try:
        # R8: policy evaluation runs on `queue` as well as the daemon tick.
        _sync_rpc_state(cfg, db)
        _apply_seeding_policy(cfg, db)
        rows = [r for r in db.list_downloads() if r.get("state") != "skipped"]
    finally:
        db.close()
    return rows


def get_status(download_id, cfg):
    db = _db(cfg)
    row = db.get_download(download_id)
    db.close()
    return row or {"error": "not found"}


def match_torrent(torrent_id: str, torrents: list[dict]) -> dict | None:
    """Match a queue id to a live torrent.

    Queue ids arrive either as Transmission's numeric RPC id (``"1"``) or as an
    infohash (full or unambiguous prefix), so both forms are resolved here.
    """
    tid = str(torrent_id or "").strip().lower()
    if not tid:
        return None
    for t in torrents:
        if str(t.get("id")) == tid:
            return t
    for t in torrents:
        h = str(t.get("hashString") or "").lower()
        if h and (h == tid or (len(tid) >= 4 and h.startswith(tid))):
            return t
    return None


def _coerce_torrent_id(torrent_id: str) -> int | str:
    s = str(torrent_id).strip()
    return int(s) if s.isdigit() else s


def _delete_media_path(path: Path, cfg: Config) -> bool:
    """Delete one raw or imported path, its sibling subtitles, and emptied dirs."""
    library = _library_root(cfg)
    p = Path(path)
    boundary = prune_boundary(p, library)
    if p.is_dir():
        removed = delete_path(p)
        if removed:
            prune_empty_dirs(p, boundary)
        return removed
    removed = False
    for sub in subtitle_files_adjacent(p):
        removed = delete_path(sub) or removed
    removed = delete_path(p) or removed
    if removed:
        prune_empty_dirs(p.parent, boundary)
    return removed


async def remove_download_and_files(
    torrent_id: str, cfg: Config, *, delete_files: bool = True
) -> dict:
    """Remove a queue item end-to-end (R1.1/R1.2).

    Resolves numeric Transmission RPC ids to their infohash, removes the torrent
    (``delete_data=True``) so staged payloads go away, deletes both the raw
    ``content_path`` and the imported ``destination_path`` files (plus sibling
    subtitles and emptied parent folders), and clears the SQLite ``downloads`` /
    ``episodes`` rows so the title is no longer reported as downloaded.
    """
    result: dict = {
        "infohash": "",
        "torrent_found": False,
        "record_found": False,
        "torrent_removed": False,
        "db_removed": False,
        "deleted_paths": [],
        "rpc_error": None,
    }
    db = _db(cfg)
    try:
        rec = db.get_download(str(torrent_id))
        rpc: RpcClient | None = None
        torrents: list[dict] = []
        rpc_error: str | None = None
        try:
            rpc = _rpc(cfg)
            torrents = await rpc.list_torrents()
        except Exception as e:
            rpc_error = str(e)

        torrent = match_torrent(str(torrent_id), torrents)
        infohash = str(torrent.get("hashString") or "").lower() if torrent else ""
        if not infohash and rec is not None:
            infohash = str(rec.get("infohash") or "")
        if not infohash:
            infohash = str(torrent_id).strip()
        if rec is None and infohash:
            rec = db.get_download(infohash)

        result["infohash"] = infohash
        result["torrent_found"] = torrent is not None
        result["record_found"] = rec is not None

        # 1. Transmission: drop the torrent and, unless disabled, its payload.
        # When listing already failed the daemon is unreachable, so there is no
        # verified target to remove and the RPC error is reported instead.
        if rpc is not None and rpc_error is None:
            cid: int | str = (
                _coerce_torrent_id(str(torrent.get("id")))
                if torrent is not None
                else _coerce_torrent_id(torrent_id)
            )
            try:
                await rpc.remove(cid, delete_data=delete_files)
                result["torrent_removed"] = True
            except Exception as e:
                rpc_error = str(e)
        result["rpc_error"] = rpc_error

        # 2. Disk: raw staging data and the imported library copy.
        if delete_files:
            paths: list[Path] = []
            for key in ("content_path", "destination_path"):
                value = rec.get(key) if rec else None
                if value:
                    paths.append(Path(str(value)))
            if torrent is not None:
                torrent_content = _torrent_content_path(torrent)
                if torrent_content is not None:
                    paths.append(torrent_content)
            for ep in db.episodes_for_download(infohash):
                if ep.get("path"):
                    paths.append(Path(str(ep["path"])))
            seen: set[str] = set()
            for p in paths:
                key = str(p)
                if key in seen:
                    continue
                seen.add(key)
                if _delete_media_path(p, cfg):
                    result["deleted_paths"].append(key)

        # 3. SQLite: the title must no longer look downloaded/imported.
        db.delete_episodes_for_download(infohash)
        record_hash = str((rec or {}).get("infohash") or infohash)
        if record_hash and db.get_download(record_hash) is not None:
            db.delete_download(record_hash)
            result["db_removed"] = True
        return result
    finally:
        db.close()


async def cancel_download(download_id, cfg, delete_data: bool = True):
    """Cancel a queue item, always removing its torrent data and local files.

    R1.1: removing a queue item deletes the torrent from Transmission, the raw
    staging folder, and the imported library file(s) so `downloads/` does not
    keep orphaned media.
    """
    result = await remove_download_and_files(str(download_id), cfg, delete_files=True)
    if not (
        result["record_found"] or result["torrent_found"] or result["deleted_paths"]
    ):
        print("Not found.", file=sys.stderr)
        raise SystemExit(3)
    if not result["torrent_removed"] and result["rpc_error"]:
        print(f"Torrent removed locally; daemon said: {result['rpc_error']}", file=sys.stderr)
    else:
        print(f"Cancelled {str(result['infohash'])[:12]}.")


async def apply_speed_limits(rpc: RpcClient, cfg: Config) -> None:
    dl = int(cfg.get("max_download_speed_kbps", 0) or 0)
    up = int(cfg.get("max_upload_speed_kbps", 0) or 0)
    if dl > 0 or up > 0:
        try:
            await rpc.set_speed_limits(download_kbps=dl, upload_kbps=up)
        except Exception:
            pass


async def pause_download(download_id: str, cfg: Config) -> bool:
    db = _db(cfg)
    rec = db.get_download(download_id)
    if not rec:
        db.close()
        print("Not found.", file=sys.stderr)
        raise SystemExit(3)
    infohash = str(rec["infohash"])
    rpc = _rpc(cfg)
    try:
        await rpc.pause_torrent(infohash)
        db.set_download_state(infohash, "paused")
        db.close()
        return True
    except Exception as e:
        db.close()
        raise e


async def resume_download(download_id: str, cfg: Config) -> bool:
    db = _db(cfg)
    rec = db.get_download(download_id)
    if not rec:
        db.close()
        print("Not found.", file=sys.stderr)
        raise SystemExit(3)
    infohash = str(rec["infohash"])
    rpc = _rpc(cfg)
    try:
        await rpc.resume_torrent(infohash)
        db.set_download_state(infohash, "downloading")
        db.close()
        return True
    except Exception as e:
        db.close()
        raise e


async def set_download_priority(download_id: str, priority: str, cfg: Config) -> bool:
    db = _db(cfg)
    rec = db.get_download(download_id)
    if not rec:
        db.close()
        print("Not found.", file=sys.stderr)
        raise SystemExit(3)
    infohash = str(rec["infohash"])
    rpc = _rpc(cfg)
    try:
        await rpc.set_torrent_priority(infohash, priority)
        db.close()
        return True
    except Exception as e:
        db.close()
        raise e


async def download_magnet(
    uri: str,
    cfg: Config,
    *,
    auto: bool = False,
    no_wait: bool = False,
) -> str:
    """Directly download and track a magnet URI or .torrent file."""
    import urllib.parse

    from guessit import guessit

    infohash = ""
    display_name = ""
    p_file = Path(uri)
    if p_file.exists() and p_file.suffix.lower() == ".torrent":
        display_name = p_file.stem
    elif uri.startswith("magnet:"):
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(uri).query)
        for xt in qs.get("xt", []):
            if xt.startswith("urn:btih:"):
                infohash = xt.split("urn:btih:")[-1].lower()
                break
        dns = qs.get("dn", [])
        if dns:
            display_name = dns[0]

    # Guess metadata from display name or path
    target_to_guess = display_name or (p_file.name if p_file.exists() else uri)
    guess = guessit(target_to_guess)
    title = str(guess.get("title") or display_name or "Unknown")
    year = guess.get("year")
    season = guess.get("season")
    episode = guess.get("episode")
    g_type = guess.get("type")

    is_tv = (season is not None) or (episode is not None) or (g_type == "episode")
    media_type = MediaType.TV if is_tv else MediaType.MOVIE

    # Metadata enrichment (best effort)
    imdb_id = None
    tmdb_id = None
    try:
        if media_type == MediaType.MOVIE:
            imdb = ImdbClient(cfg)
            m = imdb.search_movie(title)
            if m:
                imdb_id = m.get("imdb_id") or m.get("id")
                title = m.get("title") or title
                year = m.get("year") or year
        else:
            tvm = TvmazeClient(cfg)
            s = tvm.search_tv(title)
            if s:
                tmdb_id = s.get("id")
                title = s.get("name") or title
                ext = s.get("externals") or {}
                imdb_id = ext.get("imdb")
    except Exception:
        pass

    staging = _staging_dir(cfg, media_type.value)
    rpc = _rpc(cfg)
    await apply_speed_limits(rpc, cfg)

    # Ingest into Transmission
    res = await rpc.add_magnet(uri, str(staging))
    added_info = res.get("torrent-added") or res.get("torrent-duplicate") or {}
    final_hash = (added_info.get("hashString") or infohash).lower()
    final_name = added_info.get("name") or display_name or title

    if not final_hash:
        raise ValueError("Could not extract infohash from torrent")

    db = _db(cfg)
    db.add_download(
        final_hash,
        media_type=media_type.value,
        title=final_name,
        season=season if isinstance(season, int) else None,
        episode=episode if isinstance(episode, int) else None,
        year=year if isinstance(year, int) else None,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
        download_dir=str(staging),
    )
    db.set_download_state(final_hash, "downloading")
    db.close()

    print(f"Enqueued {media_type.value}: {final_name} [{final_hash[:8]}]")
    logger.info(f"Ingested magnet for {media_type.value}: '{final_name}' [{final_hash[:8]}...]")
    return final_hash


async def import_download(download_id, cfg, overwrite=False):
    db = _db(cfg)
    rec = db.get_download(download_id)
    if not rec:
        print("Not found.", file=sys.stderr)
        db.close()
        raise SystemExit(3)
    if rec.get("state") == "imported":
        destination = rec.get("destination_path")
        print(f"Already imported: {destination or '(verified)'}")
        db.close()
        return
    final = _import_record(rec, cfg, db, overwrite=overwrite)
    db.close()
    if final:
        print(f"Imported to {final}")
    else:
        print("Nothing importable found.", file=sys.stderr)
        raise SystemExit(1)


def _daemon_enqueue(series: Series, episodes: list[Episode], cfg: Config, db: DB) -> int:
    """Monitor enqueue callback (sync, runs the async work in its own loop)."""
    return asyncio.run(_enqueue_episodes(series, episodes, cfg, db))


def _poll_and_import(cfg: Config, db: DB) -> int:
    """Import any completed (non-imported) downloads. Returns count imported."""
    count = 0
    for rec in db.list_downloads():
        # only import fully-completed downloads; the staging dir exists from the
        # moment a torrent is added, so its presence is not a completion signal.
        if rec.get("state") != "completed":
            continue
        content = _resolve_content(rec, cfg=cfg)
        if content is None or not content.exists():
            continue
        final = _import_record(rec, cfg, db)
        if final:
            count += 1
    return count


def _sync_rpc_state(cfg: Config, db: DB | None = None) -> None:
    """Mark downloads completed when the daemon reports them finished (best effort)."""
    try:
        rpc = _rpc(cfg)
    except Exception:
        return

    async def _inner() -> None:
        try:
            torrents = await rpc.list_torrents()
        except Exception:
            return
        by_hash = {str(t.get("hashString", "")).lower(): t for t in torrents}
        local_db = _db(cfg)
        try:
            for rec in local_db.list_downloads():
                if rec.get("state") in ("imported", "skipped", "failed"):
                    continue
                t = by_hash.get(str(rec["infohash"]).lower())
                if not t:
                    continue
                if is_complete_torrent(t):
                    content = _torrent_content_path(t)
                    if content:
                        local_db.set_download_state(
                            rec["infohash"], "completed", content_path=str(content)
                        )
                    else:
                        local_db.set_download_state(rec["infohash"], "completed")
                elif rec.get("state") in ("added", "queued") and is_active_torrent(t):
                    local_db.set_download_state(rec["infohash"], "downloading")
        finally:
            local_db.close()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(_inner())
    else:
        try:
            asyncio.run(_inner())
        except RuntimeError:
            pass


def run_daemon(cfg):
    """Synchronous monitor loop. SIGINT/SIGTERM exits after the current tick."""
    print("Daemon tick loop (Ctrl-C to stop)...")
    import itertools

    tvm = TvmazeClient(cfg)
    for _ in itertools.count():
        db = _db(cfg)
        try:
            tick(
                db,
                cfg,
                series_fetcher=lambda tid: tvm.full_series(tid),
                enqueue=lambda s, eps: _daemon_enqueue(s, eps, cfg, db),
            )
            _sync_rpc_state(cfg, db)
            try:
                asyncio.run(_promote_queued(cfg, db))
            except RuntimeError:
                pass
            imported = _poll_and_import(cfg, db)
            if imported:
                print(f"Imported {imported} download(s).")
            _apply_seeding_policy(cfg, db)
        finally:
            db.close()
        time.sleep(int(cfg.get("monitor_poll_interval_minutes", 30)) * 60)


def _apply_seeding_policy(cfg: Config, db: DB | None = None) -> None:
    """Evaluate seeding policy for completed downloads (best effort)."""
    from arr.core.models import SeedingPolicyMode
    from arr.seeding import evaluate_torrent, validate_seeding

    try:
        mode = SeedingPolicyMode(str(cfg.get("seeding_policy", "ratio")))
    except ValueError:
        return
    try:
        validate_seeding(mode, _import_mode(cfg))
    except Exception:
        return
    try:
        rpc = _rpc(cfg)
    except Exception:
        return

    async def _inner() -> None:
        try:
            torrents = await rpc.list_torrents()
        except Exception:
            return
        by_hash = {str(t.get("hashString", "")).lower(): t for t in torrents}
        local_db = _db(cfg)
        try:
            for rec in local_db.list_downloads():
                if rec.get("state") != "imported":
                    continue
                t = by_hash.get(str(rec["infohash"]).lower())
                if not t:
                    continue
                if evaluate_torrent(
                    t,
                    mode,
                    seed_ratio=float(cfg.get("seed_ratio", 1.0)),
                    seed_time_hours=float(cfg.get("seed_time_hours", 24.0)),
                    imported=True,
                    import_mode=_import_mode(cfg),
                ):
                    try:
                        delete_data = _import_mode(cfg) != "hardlink"
                        await rpc.remove(rec["infohash"], delete_data=delete_data)
                    except Exception:
                        continue
        finally:
            local_db.close()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        loop.create_task(_inner())
    else:
        try:
            asyncio.run(_inner())
        except RuntimeError:
            pass

