from __future__ import annotations

import hashlib
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from arr.core.models import Series

JUNK_NAMES = {".ds_store", "thumbs.db"}
JUNK_EXTS = {".nfo", ".txt", ".url", ".md", ".jpg", ".png"}
MEDIA_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".m4v", ".ts", ".webm"}
SUB_EXTS = {".srt", ".ass", ".sub", ".vtt"}

# Characters illegal in Windows filenames (also stripped for cross-platform
# safety). Colon is rendered as " - " to match Sonarr/Radarr conventions.
_ILLEGAL_CHARS = '<>"/\\|?*'
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def sanitize_name(name: str) -> str:
    """Turn a human title into a filesystem-safe, Sonarr/Radarr-style name."""
    out = str(name or "").replace(":", " - ")
    for ch in _ILLEGAL_CHARS:
        out = out.replace(ch, "")
    out = re.sub(r"\s+", " ", out).strip().rstrip(" .")
    if not out:
        return "Unknown"
    if out.upper() in _WINDOWS_RESERVED:
        out = f"_{out}"
    return out


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


def find_episode_file(root: Path, season: int, episode: int) -> Path | None:
    """Locate the media file matching SxxExx (or NxNN) inside a directory."""
    tag = f"s{season:02d}e{episode:02d}"
    alt = f"{season}x{episode:02d}"
    for p in media_files(root):
        n = p.name.lower().replace(".", " ").replace("_", " ").replace("-", " ")
        if tag in n or alt in n:
            return p
    return None


def matches_episode(path: Path, season: int, episode: int) -> bool:
    tag = f"s{season:02d}e{episode:02d}"
    alt = f"{season}x{episode:02d}"
    n = path.name.lower().replace(".", " ").replace("_", " ").replace("-", " ")
    return tag in n or alt in n


def movie_dest(library_root: Path, title: str, year: int | None, ext: str) -> Path:
    safe = sanitize_name(title)
    folder = f"{safe} ({year})" if year else safe
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
    safe_show = sanitize_name(show)
    show_folder = f"{safe_show} ({year})" if year else safe_show
    season_folder = f"Season {season:02d}"
    safe_ep = sanitize_name(episode_title) if episode_title else ""
    if safe_ep:
        fname = f"{safe_show} - S{season:02d}E{episode:02d} - {safe_ep}{ext}"
    else:
        fname = f"{safe_show} - S{season:02d}E{episode:02d}{ext}"
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


def import_subtitles(
    root: Path,
    media_dst: Path,
    *,
    lang: str = "en",
    only: Callable[[Path], bool] | None = None,
) -> list[Path]:
    out = []
    for s in subtitle_files(root):
        if only is not None and not only(s):
            continue
        name = s.name.lower()
        tokens = name.replace(".", " ").replace("_", " ").replace("-", " ").split()
        langs = {"en", "eng", "english"}
        if lang == "en" and not any(t in langs for t in tokens):
            # keep only English-ish or untagged subs; skip other languages
            other = {
                "es", "spa", "fr", "fre", "de", "ger", "it", "pt", "por",
                "ja", "jp", "kr", "ko", "zh", "chs", "cht", "ru",
            }
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


def import_movie(
    content: Path,
    library_root: Path,
    title: str,
    year: int | None,
    *,
    mode: str = "hardlink",
    overwrite: bool = False,
) -> Path | None:
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
    if content.is_dir():
        matched = find_episode_file(content, season, episode)
        files = [matched] if matched is not None else media_files(content)
    else:
        files = [content]
    if not files:
        return None
    primary = max(files, key=lambda p: p.stat().st_size)
    dst = episode_dest(
        library_root, series.title, series.year, season, episode, episode_title,
        primary.suffix.lower(),
    )
    final = import_file(primary, dst, mode=mode, overwrite=overwrite)
    sub_root = content if content.is_dir() else content.parent
    import_subtitles(
        sub_root, final, only=_episode_sub_filter(sub_root, season, episode)
    )
    return final


def _normalize_name(path: Path) -> str:
    return (
        path.name.lower()
        .replace(".", " ").replace("_", " ").replace("-", " ").replace(" ", "")
    )


def _is_tagged_for(path: Path, season: int, episode: int) -> bool:
    n = _normalize_name(path)
    return f"s{season:02d}e{episode:02d}" in n or f"{season}x{episode:02d}" in n


def _has_any_episode_tag(path: Path) -> bool:
    n = _normalize_name(path)
    return bool(re.search(r"s\d{1,2}e\d{1,2}", n) or re.search(r"\d{1,2}x\d{1,2}", n))


def _episode_sub_filter(
    root: Path, season: int, episode: int
) -> Callable[[Path], bool]:
    """Select subtitles for one episode.

    Episode-tagged subtitles win; an untagged subtitle is only used when no
    tagged one exists for this episode, so an untagged file cannot take the
    primary ``<basename>.<lang>.srt`` name from the correctly tagged sibling.
    """
    subs = subtitle_files(root)
    if any(_is_tagged_for(s, season, episode) for s in subs):
        return lambda s: _is_tagged_for(s, season, episode)
    return lambda s: not _has_any_episode_tag(s)
