from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
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
    if not root.exists():
        return []
    if root.is_file():
        return [root] if root.suffix.lower() in SUB_EXTS else []
    out = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUB_EXTS:
            out.append(p)
    return out


def subtitle_files_adjacent(media_file: Path) -> list[Path]:
    """Find subtitle files sharing the base name of a single media file in the same directory."""
    parent = media_file.parent
    if not parent.exists():
        return []
    base = media_file.stem.lower()
    out = []
    try:
        for p in sorted(parent.iterdir()):
            if p.is_file() and p.suffix.lower() in SUB_EXTS:
                p_stem = p.stem.lower()
                if (
                    p_stem == base
                    or p_stem.startswith(base + ".")
                    or p_stem.startswith(base + "_")
                    or p_stem.startswith(base + "-")
                ):
                    out.append(p)
    except OSError:
        pass
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


def _import_subtitle_paths(
    subs: list[Path],
    media_dst: Path,
    *,
    lang: str = "en",
    only: Callable[[Path], bool] | None = None,
) -> list[Path]:
    out = []
    for s in subs:
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


def import_subtitles(
    root: Path,
    media_dst: Path,
    *,
    lang: str = "en",
    only: Callable[[Path], bool] | None = None,
) -> list[Path]:
    if root.is_file():
        subs = subtitle_files_adjacent(root)
    else:
        subs = subtitle_files(root)
    return _import_subtitle_paths(subs, media_dst, lang=lang, only=only)


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
    if content.is_dir():
        import_subtitles(content, final)
    else:
        _import_subtitle_paths(subtitle_files_adjacent(content), final)
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
    if content.is_dir():
        import_subtitles(
            content, final, only=_episode_sub_filter(content, season, episode)
        )
    else:
        subs = subtitle_files_adjacent(content)
        _import_subtitle_paths(
            subs, final, only=_episode_sub_filter(content.parent, season, episode)
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


def delete_path(path: Path) -> bool:
    """Delete a file (or subtree) from disk. Returns True when something was removed."""
    p = Path(path)
    try:
        if p.is_dir():
            shutil.rmtree(p)
            return True
        if p.exists():
            p.unlink()
            return True
    except OSError:
        return False
    return False


def prune_boundary(path: Path, library_root: Path) -> Path:
    """The directory `prune_empty_dirs` must never remove for `path`.

    Library media roots (`downloads/movies`, `downloads/tv-shows`) and the
    `.staging` media roots survive pruning so the layout stays intact.
    """
    p = Path(path)
    parts = p.parts
    if ".staging" in parts:
        i = parts.index(".staging")
        keep = list(parts[: i + 2]) if len(parts) > i + 1 else list(parts[: i + 1])
        return Path(*keep) if keep else Path(p.anchor or "/")
    for sub in ("movies", "tv-shows"):
        root = Path(library_root) / sub
        if root == p or root in p.parents:
            return root
    return Path(library_root)


def prune_empty_dirs(start: Path, stop_at: Path) -> int:
    """Remove empty directories from `start` upwards, never removing `stop_at`."""
    removed = 0
    stop = Path(stop_at)
    cur = Path(start)
    try:
        if cur.is_file():
            cur = cur.parent
    except OSError:
        return 0
    # Only walk directories that live strictly below the boundary directory.
    while cur != stop and stop in cur.parents:
        try:
            cur.rmdir()
        except OSError:
            break
        removed += 1
        cur = cur.parent
    return removed


def _find_ffprobe() -> str | None:
    root = Path(__file__).resolve().parents[3]
    for name in ("ffprobe.exe", "ffprobe"):
        for base in (root / "bin", Path.cwd() / "bin"):
            cand = base / name
            if cand.exists():
                return str(cand.resolve())
    return shutil.which("ffprobe")


def inspect_media_streams(path: Path) -> dict[str, list[dict]]:
    """Inspect audio, video, and subtitle streams in a media container using ffprobe."""
    empty: dict[str, list[dict]] = {"video": [], "audio": [], "subtitle": []}
    if not path.exists() or not path.is_file():
        return empty

    ffprobe = _find_ffprobe()
    if not ffprobe:
        return empty

    try:
        cmd = [
            ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_streams",
            str(path),
        ]
        res = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=30)
        data = json.loads(res.stdout)
        out: dict[str, list[dict]] = {"video": [], "audio": [], "subtitle": []}
        for st in data.get("streams", []):
            ctype = st.get("codec_type", "")
            if ctype in out:
                tags = st.get("tags", {}) or {}
                disp = st.get("disposition", {}) or {}
                lang = str(tags.get("language") or tags.get("lang") or "").lower()
                title = str(tags.get("title") or "")
                out[ctype].append(
                    {
                        "index": st.get("index", 0),
                        "codec_name": st.get("codec_name", ""),
                        "codec_type": ctype,
                        "language": lang,
                        "title": title,
                        "forced": bool(disp.get("forced", 0)),
                        "default": bool(disp.get("default", 0)),
                    }
                )
        return out
    except Exception:
        return empty


def has_embedded_subtitles(path: Path, language: str = "en") -> bool:
    """Return True if path contains an embedded subtitle track matching language."""
    streams = inspect_media_streams(path)
    sub_streams = streams.get("subtitle", [])
    if not sub_streams:
        return False

    lang_lower = language.lower()
    norm_targets = {lang_lower}
    if lang_lower == "en":
        norm_targets.update({"eng", "english"})
    elif lang_lower == "es":
        norm_targets.update({"spa", "spanish"})
    elif lang_lower == "fr":
        norm_targets.update({"fre", "fra", "french"})
    elif lang_lower == "de":
        norm_targets.update({"ger", "deu", "german"})

    for st in sub_streams:
        st_lang = (st.get("language") or "").lower()
        if st_lang in norm_targets:
            return True
        st_title = (st.get("title") or "").lower()
        if any(t in st_title for t in norm_targets):
            return True

    return False
