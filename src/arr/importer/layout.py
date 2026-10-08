from __future__ import annotations

import errno
import hashlib
import os
import shutil
from pathlib import Path

from arr.core.models import Series

JUNK_NAMES = {".ds_store", "thumbs.db"}
JUNK_EXTS = {".nfo", ".txt", ".url", ".md", ".jpg", ".png"}
MEDIA_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".ts", ".webm"}
SUB_EXTS = {".srt", ".ass", ".sub", ".vtt"}


def _sha1(path: Path, limit: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        h.update(f.read(limit))
    return h.hexdigest()


def is_junk(path: Path) -> bool:
    name = path.name.lower()
    if name in JUNK_NAMES:
        return True
    if path.suffix.lower() in JUNK_EXTS:
        return True
    parts = {p.lower() for p in path.parts}
    if "sample" in parts or "extras" in parts:
        return True
    return False


def media_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in MEDIA_EXTS and not is_junk(p.relative_to(root)):
            out.append(p)
    return out


def subtitle_files(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUB_EXTS:
            out.append(p)
    return out


def movie_dest(library_root: Path, title: str, year: int | None, ext: str) -> Path:
    folder = f"{title} ({year})" if year else title
    return library_root / "movies" / folder / f"{folder}{ext}"


def episode_dest(
    library_root: Path,
    show: str,
    year: int | None,
    season: int,
    episode: int,
    episode_title: str,
    ext: str,
) -> Path:
    show_folder = f"{show} ({year})" if year else show
    season_folder = f"Season {season:02d}"
    fname = f"{show} - S{season:02d}E{episode:02d} - {episode_title}{ext}"
    return library_root / "tv-shows" / show_folder / season_folder / fname


def _transfer(src: Path, dst: Path, mode: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if mode == "move":
        shutil.move(str(src), str(dst))
        return
    if mode == "copy":
        shutil.copy2(str(src), str(dst))
        return
    # hardlink default
    try:
        os.link(str(src), str(dst))
    except OSError:
        # cross-device (EXDEV) or hardlink unsupported -> copy fallback
        shutil.copy2(str(src), str(dst))


def _collision_path(dst: Path) -> Path:
    for i in range(1, 100):
        cand = dst.with_name(f"{dst.stem}.{i}{dst.suffix}")
        if not cand.exists():
            return cand
    return dst


def import_file(src: Path, dst: Path, *, mode: str = "hardlink", overwrite: bool = False) -> Path:
    """Import one media file. Returns final destination path."""
    if dst.exists():
        if overwrite:
            dst.unlink()
        else:
            # same size + partial hash => treat as identical
            try:
                if dst.stat().st_size == src.stat().st_size and _sha1(dst) == _sha1(src):
                    return dst
            except OSError:
                pass
            dst = _collision_path(dst)
    _transfer(src, dst, mode)
    return dst


def rename_subtitle(src: Path, media_dst: Path, lang: str = "en") -> Path:
    return src.with_name(f"{media_dst.stem}.{lang}{src.suffix}")


def import_subtitles(root: Path, media_dst: Path, *, lang: str = "en") -> list[Path]:
    out = []
    for s in subtitle_files(root):
        name = s.name.lower()
        tokens = name.replace(".", " ").replace("_", " ").replace("-", " ").split()
        langs = {"en", "eng", "english"}
        if lang == "en" and not any(t in langs for t in tokens):
            # keep only English-ish or untagged subs; skip other languages
            other = {"es", "spa", "fr", "fre", "de", "ger", "it", "pt", "por", "ja", "jp", "kr", "ko", "zh", "chs", "cht", "ru"}
            if any(t in other for t in tokens):
                continue
        target_dir = media_dst.parent
        target = target_dir / f"{media_dst.stem}.{lang}{s.suffix}"
        if target.exists():
            target = _collision_path(target)
        try:
            os.link(str(s), str(target))
        except OSError:
            shutil.copy2(str(s), str(target))
        out.append(target)
    return out


def import_movie(content: Path, library_root: Path, title: str, year: int | None, *, mode: str = "hardlink", overwrite: bool = False) -> Path | None:
    files = media_files(content) if content.is_dir() else [content]
    if not files:
        return None
    primary = max(files, key=lambda p: p.stat().st_size)
    dst = movie_dest(library_root, title, year, primary.suffix.lower())
    final = import_file(primary, dst, mode=mode, overwrite=overwrite)
    import_subtitles(content if content.is_dir() else content.parent, final)
    return final


def import_episode(
    content: Path,
    library_root: Path,
    series: Series,
    season: int,
    episode: int,
    episode_title: str,
    *,
    mode: str = "hardlink",
    overwrite: bool = False,
) -> Path | None:
    files = media_files(content) if content.is_dir() else [content]
    if not files:
        return None
    primary = max(files, key=lambda p: p.stat().st_size)
    dst = episode_dest(library_root, series.title, series.year, season, episode, episode_title, primary.suffix.lower())
    final = import_file(primary, dst, mode=mode, overwrite=overwrite)
    import_subtitles(content if content.is_dir() else content.parent, final)
    return final
