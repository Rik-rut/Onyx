from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from arr.config.settings import Config
from arr.db import DB
from arr.subtitles.base import SubtitleError, rank_candidates
from arr.subtitles.subscene import SubsceneClient
from arr.subtitles.yify import YifySubtitlesClient


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def convert_to_srt(src: Path, dst: Path) -> bool:
    """Convert .ass/.sub to .srt via ffmpeg when available. Returns True on success."""
    if ffmpeg_available():
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), str(dst)],
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

    Priority: sibling subtitle already next to the file (imported by importer) →
    Subscene → YIFY fallback → record missing. Returns list of db records.
    """
    results: list[dict] = []
    if not cfg.get("subtitles_enabled", True):
        return results
    languages = list(cfg.get("subtitle_languages", ["en"]) or ["en"])
    forced = bool(cfg.get("subtitles_forced_only", False))
    base = media_path.with_suffix("")

    for lang in languages:
        # 1) sibling/embedded already placed by the importer
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
                break
        else:
            # 2) Subscene → YIFY fallback
            subscene_base = str(cfg.get("subscene_base_url", "https://subscene.com"))
            yify_base = str(cfg.get("yify_subtitles_base_url", "https://yifysubtitles.ch"))
            placed = False
            for source, client in (
                ("subscene", SubsceneClient(subscene_base)),
                ("yify", YifySubtitlesClient(yify_base)),
            ):
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
                    break
                except SubtitleError as e:
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
            if not placed:
                db.add_subtitle(str(media_path), lang, "missing", "missing", None)
                results.append(
                    {"language": lang, "path": None, "source": "missing", "state": "missing"}
                )
    return results

