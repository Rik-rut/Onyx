from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from arr.config.settings import Config
from arr.db import DB
from arr.importer.layout import has_embedded_subtitles
from arr.subtitles.addic7ed import Addic7edClient
from arr.subtitles.base import SubtitleProvider, rank_candidates
from arr.subtitles.subdl import SubdlClient
from arr.subtitles.subscene import SubsceneClient
from arr.subtitles.yify import YifySubtitlesClient


def _find_ffmpeg() -> str | None:
    root = Path(__file__).resolve().parents[3]
    for name in ("ffmpeg.exe", "ffmpeg"):
        for base in (root / "bin", Path.cwd() / "bin"):
            cand = base / name
            if cand.exists():
                return str(cand.resolve())
    return shutil.which("ffmpeg")


def ffmpeg_available() -> bool:
    return _find_ffmpeg() is not None


def convert_to_srt(src: Path, dst: Path) -> bool:
    """Convert .ass/.sub to .srt via ffmpeg when available. Returns True on success."""
    binary = _find_ffmpeg()
    if binary:
        try:
            subprocess.run(
                [binary, "-y", "-i", str(src), str(dst)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=120,
            )
            return dst.exists()
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return False
    # no ffmpeg: copy with renamed extension preserved (documented behavior)
    try:
        shutil.copy2(str(src), str(dst.with_suffix(src.suffix)))
        return True
    except OSError:
        return False


def ensure_subtitles(
    media_path: Path,
    *,
    cfg: Config,
    db: DB,
    imdb_id: str | None = None,
    tmdb_id: int | None = None,
    season: int | None = None,
    episode: int | None = None,
    release_name: str = "",
) -> list[dict]:
    """Ensure <media basename>.<lang>.<ext> exists next to the media file.

    Priority: embedded subtitle track in container -> sibling subtitle already
    next to the file -> TV provider (Addic7ed / SubDL) / Movie provider (YIFY / SubDL)
    -> Subscene fallback -> record missing. Returns list of db records.
    """
    results: list[dict] = []
    if not cfg.get("subtitles_enabled", True):
        return results
    languages = list(cfg.get("subtitle_languages", ["en"]) or ["en"])
    forced = bool(cfg.get("subtitles_forced_only", False))
    base = media_path.with_suffix("")

    # Best-effort metadata resolution if imdb_id is missing
    if not imdb_id:
        lookup_title = ""
        if release_name:
            try:
                from guessit import guessit

                g = guessit(release_name)
                lookup_title = str(g.get("title") or release_name)
            except Exception:
                lookup_title = release_name
        if not lookup_title:
            lookup_title = media_path.stem

        try:
            from arr.metadata.imdb import ImdbClient
            from arr.metadata.tvmaze import TvmazeClient

            is_tv = season is not None and episode is not None
            if is_tv:
                tvm = TvmazeClient(cfg)
                s = tvm.search_tv(lookup_title)
                if s:
                    if not tmdb_id:
                        tmdb_id = s.get("id")
                    ext = s.get("externals") or {}
                    imdb_id = ext.get("imdb")
            else:
                imdb = ImdbClient(cfg)
                m = imdb.search_movie(lookup_title)
                if m:
                    imdb_id = m.get("imdb_id") or m.get("id")
                    if not tmdb_id and m.get("tmdb_id"):
                        tmdb_id = m.get("tmdb_id")
        except Exception as e:
            print(f"warning: metadata lookup in ensure_subtitles failed: {e}", file=sys.stderr)

    acquired = False
    for lang in languages:
        # 0) Embedded subtitle track in the media file container
        if has_embedded_subtitles(media_path, lang):
            db.add_subtitle(str(media_path), lang, "embedded", "ok", None)
            results.append(
                {"language": lang, "path": str(media_path), "source": "embedded", "state": "ok"}
            )
            acquired = True
            break

        # 1) Sibling subtitle already placed by the importer
        found_sibling = False
        for ext in (".srt", ".ass", ".sub", ".vtt"):
            cand = media_path.parent / f"{base.name}.{lang}{ext}"
            if cand.exists():
                source = "sibling"
                if ext != ".srt" and ffmpeg_available():
                    converted = media_path.parent / f"{base.name}.{lang}.srt"
                    if convert_to_srt(cand, converted) and converted.exists():
                        cand = converted
                        source = "embedded" if ext in (".ass", ".sub") else "sibling"
                db.add_subtitle(str(media_path), lang, source, "ok", None)
                results.append(
                    {"language": lang, "path": str(cand), "source": source, "state": "ok"}
                )
                found_sibling = True
                acquired = True
                break
        if found_sibling:
            break

        # 2) External subtitle providers
        addic7ed_base = str(cfg.get("addic7ed_base_url", "https://www.addic7ed.com"))
        subdl_base = str(cfg.get("subdl_base_url", "https://api.subdl.com"))
        subdl_key = str(cfg.get("subdl_api_key", ""))
        subscene_base = str(cfg.get("subscene_base_url", "https://subscene.com"))
        yify_base = str(cfg.get("yify_subtitles_base_url", "https://yifysubtitles.ch"))

        is_tv = season is not None and episode is not None
        providers: list[tuple[str, SubtitleProvider]]
        if is_tv:
            providers = [
                ("addic7ed", Addic7edClient(addic7ed_base)),
                ("subdl", SubdlClient(subdl_base, api_key=subdl_key)),
                ("subscene", SubsceneClient(subscene_base)),
            ]
        else:
            providers = [
                ("yify", YifySubtitlesClient(yify_base)),
                ("subdl", SubdlClient(subdl_base, api_key=subdl_key)),
                ("subscene", SubsceneClient(subscene_base)),
            ]

        placed = False
        for source, client in providers:
            try:
                cands = client.search(
                    imdb_id=imdb_id,
                    tmdb_id=tmdb_id,
                    title=release_name or None,
                    season=season,
                    episode=episode,
                    languages=[lang],
                )
                ranked = rank_candidates(cands, release_name=release_name, forced_only=forced)
                if not ranked:
                    continue
                top = ranked[0]
                data = client.download(top)
                dst = media_path.parent / f"{base.name}.{lang}.srt"
                dst.write_bytes(data)
                db.add_subtitle(str(media_path), lang, source, "ok", top.subtitle_id)
                results.append(
                    {
                        "language": lang,
                        "path": str(dst),
                        "source": source,
                        "state": "ok",
                        "subtitle_id": top.subtitle_id,
                    }
                )
                placed = True
                acquired = True
                break
            except Exception as e:
                print(f"warning: {source} subtitle lookup failed: {e}", file=sys.stderr)
                db.add_subtitle(str(media_path), lang, source, "error", None)
                results.append(
                    {
                        "language": lang,
                        "path": None,
                        "source": source,
                        "state": f"error: {e}",
                    }
                )
                continue
        if placed:
            break

    if not acquired:
        primary_lang = languages[0] if languages else "en"
        db.add_subtitle(str(media_path), primary_lang, "missing", "missing", None)
        results.append(
            {"language": primary_lang, "path": None, "source": "missing", "state": "missing"}
        )
    return results

