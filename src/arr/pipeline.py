from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from arr.config.settings import Config
from arr.core.models import Episode, MediaType, QualityProfile, Query, Release, Series
from arr.core.parsing import explain, rank
from arr.db import DB
from arr.importer.layout import (
    find_episode_file,
    import_episode,
    import_movie,
    media_files,
)
from arr.indexers import build_adapters
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
    is_active_torrent,
    is_complete_torrent,
    plan_slots,
)

DB_PATH = Path(".cache") / "arr" / "arr.db"


def _db(cfg: Config) -> DB:
    root = Path(str(cfg.get("library_root", "downloads"))).parent
    path = root / ".cache" / "arr" / "arr.db"
    return DB(path)


def _rpc(cfg: Config) -> RpcClient:
    return RpcClient(
        str(cfg.get("transmission_rpc_host", "127.0.0.1")),
        int(cfg.get("transmission_rpc_port", 9091)),
        str(cfg.get("transmission_rpc_user", "") or ""),
        str(cfg.get("transmission_rpc_pass", "") or ""),
    )


def _library_root(cfg: Config) -> Path:
    return Path(str(cfg.get("library_root", "downloads")))


def _staging_dir(cfg: Config, media_type: str) -> Path:
    sub = "movies" if media_type == "movie" else "tv-shows"
    d = Path(str(cfg.get("download_root", "downloads"))) / sub / ".incomplete"
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
            "Note: importing via hardlink keeps torrent data in .incomplete/ so seeding "
            "can continue (the library shares the same blocks)."
        )
        suffix = f" ({count} torrents)" if count > 1 else ""
        print(notice + suffix)

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
    "_import_record",
    "_enqueue_episodes",
    "_enqueue_series_query",
    "_poll_and_import",
]


async def search(
    media_type: MediaType,
    query: str,
    cfg: Config,
    season: int | None = None,
    episode: int | None = None,
    explain_mode: bool = False,
) -> list[Release]:
    q = Query(media_type=media_type, text=query, season=season, episode=episode)
    # Metadata resolve (best effort)
    try:
        if media_type == MediaType.MOVIE:
            imdb = ImdbClient(cfg)
            m = imdb.search_movie(query)
            if m:
                q.imdb_id = m.get("imdb_id") or m.get("id")
                q.title = m.get("title")
                q.year = m.get("year")
        else:
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
    if explain_mode:
        print(explain(scored), file=sys.stderr)
    return [s.release for s in scored if s.rejected is None]


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
    if existing and not force:
        print(f"Already known (state={existing['state']}); use --force to re-add.")
        db.close()
        return
    staging = _staging_dir(cfg, "movie")
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
    db.add_download(
        chosen.infohash,
        media_type="movie",
        tmdb_id=chosen.tmdb_id,
        imdb_id=chosen.imdb_id,
        title=chosen.title,
        year=chosen.year,
        indexer=chosen.indexer,
        download_dir=str(staging),
        state="queued" if paused else "added",
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
    if existing and not force:
        return 0
    staging = _staging_dir(cfg, "tv")
    try:
        await _rpc(cfg).add_magnet(chosen.magnet, str(staging))
    except DependencyUnavailable as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(4)
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
            if pack.infohash in seen_hashes or db.get_download(pack.infohash):
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
            if chosen.infohash in seen_hashes or db.get_download(chosen.infohash):
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
        try:
            await rpc.add_magnet(chosen.magnet, str(staging), paused=paused)
        except DependencyUnavailable as e:
            print(str(e), file=sys.stderr)
            raise SystemExit(4)
        lead = covered[0]
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
            state="queued" if paused else "added",
        )
        state = "queued" if paused else "added"
        for ep in covered:
            db.set_episode_state(
                series.tmdb_id, ep.season_number, ep.episode_number, state,
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
    root = _library_root(cfg) / "tv-shows"
    title = str(series["title"])
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


def _import_record(rec: dict, cfg: Config, db: DB, *, overwrite: bool = False) -> Path | None:
    """Import one completed download's content into the library. Idempotent."""
    content = Path(str(rec.get("content_path") or rec.get("download_dir") or ""))
    if not content.exists():
        return None
    media_type = rec.get("media_type")
    mode = _import_mode(cfg)
    library = _library_root(cfg)

    if media_type == "movie":
        final = import_movie(
            content,
            library,
            rec.get("title") or "Unknown",
            rec.get("year"),
            mode=mode,
            overwrite=overwrite,
        )
        if final:
            db.set_download_state(rec["infohash"], "imported", destination_path=str(final))
            ensure_subtitles(
                final,
                cfg=cfg,
                db=db,
                imdb_id=rec.get("imdb_id"),
                tmdb_id=rec.get("tmdb_id"),
                release_name=rec.get("title") or "",
            )
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
        final = import_episode(
            primary, library, series, int(season), int(episode),
            rec.get("episode_title") or "", mode=mode, overwrite=overwrite,
        )
        if final:
            db.set_episode_state(
                series.tmdb_id, int(season), int(episode), "imported", path=str(final)
            )
            ensure_subtitles(
                final, cfg=cfg, db=db, imdb_id=series.imdb_id, tmdb_id=series.tmdb_id,
                season=int(season), episode=int(episode), release_name=rec.get("title") or "",
            )
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
    if imported:
        mark_pack_imported(db, series, season)
        db.set_download_state(rec["infohash"], "imported", destination_path=str(last))
    return last


async def series_check(series_id, cfg):
    db = _db(cfg)
    rows = [r for r in db.list_monitored() if int(r["id"]) == int(series_id)]
    if not rows:
        print("No such series.", file=sys.stderr)
        raise SystemExit(3)
    tvm = TvmazeClient(cfg)
    series = tvm.full_series(int(rows[0]["tmdb_id"]))
    wanted = select_airing(series, db, lookahead_days=int(cfg.get("monitor_lookahead_days", 7)))
    print(f"{len(wanted)} episode(s) due for {series.title}")
    db.close()


def list_queue(cfg):
    db = _db(cfg)
    rows = db.list_downloads()
    db.close()
    return rows


def get_status(download_id, cfg):
    db = _db(cfg)
    row = db.get_download(download_id)
    db.close()
    return row or {"error": "not found"}


async def cancel_download(download_id, cfg, delete_data=False):
    try:
        rpc = _rpc(cfg)
        await rpc.remove(download_id, delete_data=delete_data)
    except DependencyUnavailable:
        pass
    db = _db(cfg)
    db.set_download_state(download_id, "skipped")
    db.close()


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
        if rec.get("state") in ("imported", "skipped", "failed"):
            continue
        content = Path(str(rec.get("content_path") or rec.get("download_dir") or ""))
        if not content.exists():
            continue
        final = _import_record(rec, cfg, db)
        if final:
            count += 1
    return count


def _sync_rpc_state(cfg: Config, db: DB) -> None:
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
        for rec in db.list_downloads():
            if rec.get("state") in ("imported", "skipped", "failed"):
                continue
            t = by_hash.get(str(rec["infohash"]).lower())
            if not t:
                continue
            if is_complete_torrent(t):
                content = _torrent_content_path(t)
                if content:
                    db.set_download_state(rec["infohash"], "completed", content_path=str(content))
                else:
                    db.set_download_state(rec["infohash"], "completed")
            elif rec.get("state") in ("added", "queued") and is_active_torrent(t):
                db.set_download_state(rec["infohash"], "downloading")

    try:
        asyncio.run(_inner())
    except RuntimeError:
        return


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


def _apply_seeding_policy(cfg: Config, db: DB) -> None:
    """Evaluate seeding policy for completed downloads (best effort)."""
    from arr.core.models import SeedingPolicyMode
    from arr.seeding import should_remove, validate_seeding

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
        for rec in db.list_downloads():
            if rec.get("state") != "imported":
                continue
            t = by_hash.get(str(rec["infohash"]).lower())
            if not t:
                continue
            ratio = t.get("uploadRatio")
            if should_remove(
                mode,
                ratio=float(ratio) if ratio is not None else None,
                seed_ratio=float(cfg.get("seed_ratio", 1.0)),
                imported=True,
                import_mode=_import_mode(cfg),
            ):
                try:
                    await rpc.remove(rec["infohash"], delete_data=_import_mode(cfg) != "hardlink")
                except Exception:
                    continue

    try:
        asyncio.run(_inner())
    except RuntimeError:
        return

