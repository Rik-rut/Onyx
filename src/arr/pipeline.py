from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from arr.config.settings import Config, default_config_path
from arr.core.models import MediaType, QualityProfile, Query, Release, Series
from arr.core.parsing import explain, rank
from arr.db import DB
from arr.importer.layout import import_episode, import_movie
from arr.indexers import build_adapters
from arr.metadata.tmdb import TmdbClient, TmdbError, degrade
from arr.monitor.loop import select_airing, tick
from arr.series.orchestration import mark_pack_imported, needed_episodes, resolve_scope
from arr.subtitles.service import ensure_subtitles
from arr.transmission.errors import DependencyUnavailable
from arr.transmission.process import ConcurrencyGate, RpcClient, find_daemon, find_remote

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


async def search(
    media_type: MediaType,
    query: str,
    cfg: Config,
    season: int | None = None,
    episode: int | None = None,
    explain_mode: bool = False,
) -> list[Release]:
    q = Query(media_type=media_type, text=query, season=season, episode=episode)
    # TMDB resolve (best effort)
    try:
        tmdb = TmdbClient(cfg)
        if media_type == MediaType.MOVIE:
            m = tmdb.search_movie(query)
            if m:
                q.tmdb_id = m.get("id")
                q.title = m.get("title")
        else:
            s = tmdb.search_tv(query)
            if s:
                q.tmdb_id = s.get("id")
                q.title = s.get("name")
                try:
                    ext = tmdb.tv_external_ids(s["id"])
                    q.imdb_id = ext.get("imdb_id")
                except TmdbError:
                    pass
    except TmdbError as e:
        degrade(query)
        print(f"warning: TMDB lookup failed: {e}", file=sys.stderr)

    adapters = [a for a in build_adapters(cfg) if a.supports(media_type)]
    search_text = q.title or query
    q.text = search_text

    async def _one(a):
        try:
            return await asyncio.wait_for(a.search(q), timeout=30.0)
        except Exception as e:
            print(f"warning: indexer {a.name} failed: {e}", file=sys.stderr)
            return []

    results = await asyncio.gather(*[_one(a) for a in adapters])
    releases: list[Release] = []
    for group in results:
        releases.extend(group)

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


async def download_movie(query, cfg, *, pick=None, auto=False, yes=False, no_wait=False, force=False):
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
        return
    incomple = Path(str(cfg.get("download_root", "downloads"))) / "movies" / ".incomplete"
    incomple.mkdir(parents=True, exist_ok=True)
    try:
        rpc = _rpc(cfg)
        await rpc.add_magnet(chosen.magnet, str(incomple))
    except DependencyUnavailable as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(4)
    db.add_download(
        chosen.infohash,
        media_type="movie",
        tmdb_id=chosen.tmdb_id,
        title=chosen.title,
        indexer=chosen.indexer,
        download_dir=str(incomple),
        state="added",
    )
    if no_wait:
        print("Added (no-wait).")
        return
    # poll until completed (bounded), then import
    deadline = time.time() + 3600
    while time.time() < deadline:
        try:
            t = await rpc.get(chosen.infohash)
        except DependencyUnavailable:
            break
        if t and (t.get("status") in (4, 6) or t.get("percentDone", 0) >= 1.0):
            db.set_download_state(chosen.infohash, "completed", content_path=t.get("downloadDir"))
            break
        await asyncio.sleep(5)
    rec = db.get_download(chosen.infohash)
    content = Path(str((rec or {}).get("content_path") or incomple))
    if content.exists():
        final = import_movie(content, Path(str(cfg.get("library_root", "downloads"))), chosen.title, chosen.year, mode=str(cfg.get("import_mode", "hardlink")))
        if final:
            db.set_download_state(chosen.infohash, "imported", destination_path=str(final))
            ensure_subtitles(final, cfg=cfg, db=db, tmdb_id=chosen.tmdb_id, release_name=chosen.title)
            print(f"Imported to {final}")
    db.close()


async def download_tv(query, cfg, *, season=None, episode=None, pack=False, pick=None, auto=False, yes=False, no_wait=False, force=False):
    releases = await search(MediaType.TV, query, cfg, season=season, episode=episode)
    if not releases:
        print("No results.", file=sys.stderr)
        raise SystemExit(3)
    scope = "entire series" if season is None and episode is None else (f"S{season}" if episode is None else f"S{season}E{episode}")
    print(f"Scope: {scope} ({len(releases)} candidate releases)")
    if not yes:
        if input("Start download? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Aborted.")
            return
    chosen = _pick(releases, auto, pick)
    if chosen is None:
        print("No selection.", file=sys.stderr)
        raise SystemExit(2)
    db = _db(cfg)
    incomple = Path(str(cfg.get("download_root", "downloads"))) / "tv-shows" / ".incomplete"
    incomple.mkdir(parents=True, exist_ok=True)
    try:
        rpc = _rpc(cfg)
        await rpc.add_magnet(chosen.magnet, str(incomple))
    except DependencyUnavailable:
        raise SystemExit(4)
    db.add_download(chosen.infohash, media_type="tv", title=chosen.title, season=season, episode=episode, indexer=chosen.indexer, download_dir=str(incomple), state="added")
    print(f"Added: {chosen.title}")
    db.close()


async def series_add(query, cfg):
    try:
        tmdb = TmdbClient(cfg)
        s = tmdb.search_tv(query)
        if not s:
            print("No series found.", file=sys.stderr)
            raise SystemExit(3)
        series = tmdb.full_series(s["id"])
    except TmdbError as e:
        print(f"TMDB error: {e}", file=sys.stderr)
        raise SystemExit(4)
    db = _db(cfg)
    sid = db.add_monitored(series.tmdb_id, series.title, series.imdb_id, series.status, None)
    print(f"Added monitored series: {series.title} ({series.status}) id={sid}")
    db.close()


def series_list(cfg):
    db = _db(cfg)
    rows = db.list_monitored()
    out = []
    for r in rows:
        eps = db.episodes_for_series(int(r["tmdb_id"]))
        imported = sum(1 for e in eps if e["state"] == "imported")
        out.append({"id": r["id"], "title": r["title"], "status": r["status"], "last_checked_at": r["last_checked_at"], "imported_episodes": imported})
    db.close()
    return out


def series_remove(series_id, cfg, delete_files=False):
    db = _db(cfg)
    db.remove_monitored(int(series_id))
    db.close()
    print(f"Removed monitored series {series_id}")


async def series_check(series_id, cfg):
    db = _db(cfg)
    rows = [r for r in db.list_monitored() if int(r["id"]) == int(series_id)]
    if not rows:
        print("No such series.", file=sys.stderr)
        raise SystemExit(3)
    tmdb = TmdbClient(cfg)
    series = tmdb.full_series(int(rows[0]["tmdb_id"]))
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
        raise SystemExit(3)
    content = Path(str(rec.get("download_dir") or ""))
    print(f"Import for {download_id} from {content}")
    db.close()


async def run_daemon(cfg):
    print("Daemon tick loop (Ctrl-C to stop)...")
    import itertools

    for _ in itertools.count():
        db = _db(cfg)
        try:
            tick(db, cfg, series_fetcher=lambda tid: TmdbClient(cfg).full_series(tid), enqueue=lambda s, eps: len(eps))
        finally:
            db.close()
        await asyncio.sleep(int(cfg.get("monitor_poll_interval_minutes", 30)) * 60)

