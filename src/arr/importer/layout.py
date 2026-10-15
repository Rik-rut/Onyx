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
    """Find subtitle files sharing the base name of a single media file in the same directory.

    The remainder after the media stem must be a language tag (optionally with a
    variant/index), so deleting `Movie (2018).mkv` never strips the subtitles of
    a sibling `Movie (2018).2.mkv`.
    """
    parent = media_file.parent
    if not parent.exists():
        return []
    base = media_file.stem.lower()
    out = []
    try:
        for p in sorted(parent.iterdir()):
            if p.is_file() and p.suffix.lower() in SUB_EXTS:
                p_stem = p.stem.lower()
                if p_stem == base:
                    out.append(p)
                    continue
                for sep in (".", "_", "-"):
                    prefix = base + sep
                    if not p_stem.startswith(prefix):
                        continue
                    remainder = p_stem[len(prefix):].replace("_", " ").replace("-", " ").split()
                    if remainder and remainder[0] in _LANG_ALIASES or (
                        remainder and remainder[0] in _LANG_CODES
                    ):
                        out.append(p)
                    break
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


_YEAR_FOLDER_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<year>(?:19|20)\d{2})\)\s*$")
_BRACKETS_RE = re.compile(r"[\[\]()]")
_RAW_TOKEN_RE = re.compile(
    r"(?:\b\d{3,4}p\b|\b4k\b|\buhd\b|\bbluray\b|\bblu-ray\b|\bbrrip\b|\bbdrip\b|"
    r"\bwebrip\b|\bweb-dl\b|\bwebdl\b|\bhdtv\b|\bdvdrip\b|\bhdrip\b|\bremux\b|"
    r"\bx26[45]\b|\bh26[45]\b|\bhevc\b|\bavc\b|\baac\b|\bac3\b|\bdts\b|\bddp\b|"
    r"\b10bit\b|\b8bit\b|\bs\d{1,2}e\d{1,2}\b|\bs\d{1,2}\b|\byts\b|\byify\b)",
    re.I,
)
_LANG_ALIASES = {
    "eng": "en", "english": "en", "spa": "es", "spanish": "es", "fre": "fr",
    "fra": "fr", "french": "fr", "ger": "de", "deu": "de", "german": "de",
    "ita": "it", "italian": "it", "por": "pt", "pt-br": "pt", "jpn": "ja",
    "jap": "ja", "jp": "ja", "japanese": "ja", "kor": "ko", "korean": "ko",
    "chi": "zh", "chs": "zh", "cht": "zh", "rus": "ru",
}
# Only these may be read as a subtitle language — a title word like "Fu" in
# "Kung Fu Panda" must not become a ".fu.srt" tag.
_LANG_CODES = {
    "en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh", "ru", "ar", "nl",
    "pl", "tr", "sv", "no", "da", "fi", "cs", "el", "he", "hi", "th", "vi",
    "id", "uk", "ro", "hu", "bg", "hr", "sr", "sk", "sl", "fa", "ta", "te",
    "ml", "bn",
}


def is_clean_folder_name(name: str) -> bool:
    """`<Title> (<Year>)` — the single-folder layout Onyx imports into."""
    return bool(_YEAR_FOLDER_RE.match(str(name).strip()))


def folder_title(name: str) -> str:
    """The title part of a clean folder name (`Show (2025)` -> `Show`)."""
    m = _YEAR_FOLDER_RE.match(str(name).strip())
    return (m.group("title") if m else str(name)).strip()


def looks_like_raw_release(name: str) -> bool:
    """True when a folder name carries release tags, i.e. a raw torrent folder."""
    n = str(name).strip()
    if not n or n.startswith("."):
        return False
    if is_clean_folder_name(n):
        return False
    return bool(_RAW_TOKEN_RE.search(_BRACKETS_RE.sub(" ", n)))


def parse_raw_release_name(name: str) -> tuple[str, int | None]:
    """Best-effort `(title, year)` for a raw release folder name."""
    n = re.sub(r"\s+", " ", _BRACKETS_RE.sub(" ", str(name))).strip()
    year: int | None = None
    m = re.search(r"\b((?:19|20)\d{2})\b", n)
    if m:
        year = int(m.group(1))
        n = n[: m.start()]
    tag = _RAW_TOKEN_RE.search(n)
    if tag:
        n = n[: tag.start()]
    title = sanitize_name(n.replace(".", " ").replace("_", " ").strip())
    return title, year


def subtitle_language(path: Path, default: str = "en") -> str:
    """Language code for a subtitle file name (`Show.en.srt` -> ``en``).

    Only known ISO 639-1 codes and their aliases count, so release-title words
    (``Kung.Fu.Panda...``) are never mistaken for a language.
    """
    tokens = (
        path.stem.lower().replace(".", " ").replace("_", " ").replace("-", " ").split()
    )
    for token in reversed(tokens):
        if token in _LANG_ALIASES:
            return _LANG_ALIASES[token]
        if token in _LANG_CODES:
            return token
    return default


def _carry_subtitles(raw_dir: Path, media_dst: Path) -> int:
    """Copy subtitles the clean folder is missing (raw folder is being deleted)."""
    existing = {p.name.lower() for p in subtitle_files_adjacent(media_dst)}
    carried = 0
    for sub in subtitle_files(raw_dir):
        target = media_dst.parent / f"{media_dst.stem}.{subtitle_language(sub)}{sub.suffix}"
        if target.name.lower() in existing or target.exists():
            continue
        try:
            os.link(str(sub), str(target))
        except OSError:
            try:
                shutil.copy2(str(sub), str(target))
            except OSError:
                continue
        existing.add(target.name.lower())
        carried += 1
    return carried


def _clean_folder_match(title: str, year: int | None, folders: list[Path]) -> Path | None:
    safe = sanitize_name(title).lower()
    if year:
        target = f"{safe} ({year})"
        for folder in folders:
            if folder.name.lower() == target:
                return folder
        return None
    for folder in folders:
        if folder_title(folder.name).lower() == safe:
            return folder
    for folder in folders:
        if folder.name.lower().startswith(f"{safe} ("):
            return folder
    return None


def _verify_clean_movie(target: Path, raw: Path, *, mode: str) -> None:
    """Make sure the surviving clean folder holds the movie and its subtitles."""
    media = media_files(target)
    if not media:
        files = media_files(raw)
        if files:
            primary = max(files, key=lambda p: p.stat().st_size)
            dst = target / f"{target.name}{primary.suffix.lower()}"
            final = import_file(primary, dst, mode=mode)
            _carry_subtitles(raw, final)
        return
    primary = max(media, key=lambda p: p.stat().st_size)
    _carry_subtitles(raw, primary)


def _episode_tags(media: Path, raw_dir: Path) -> tuple[int | None, int | None]:
    """Season/episode numbers for one raw episode file (folder name as fallback)."""
    from arr.core.parsing import parse_release

    parsed = parse_release(media.name) or {}
    season = parsed.get("season")
    episode = parsed.get("episode")
    season = int(season) if isinstance(season, int) else None
    episode = int(episode) if isinstance(episode, int) else None
    if season is None:
        m = re.search(r"(?:^|[^a-z])[Ss](\d{1,2})(?:[^0-9]|$)", raw_dir.name)
        if m:
            season = int(m.group(1))
    return season, episode


def _import_missing_episodes(raw: Path, show: Path, library_root: Path, *, mode: str) -> int:
    """Move episodes the clean show folder does not have; drop duplicate raw copies.

    Returns the number of media files that could not be attributed to an episode
    (those keep the raw folder alive).
    """
    show_title = folder_title(show.name)
    unplaced = 0
    for media in list(media_files(raw)):
        season, episode = _episode_tags(media, raw)
        if season is None or episode is None:
            unplaced += 1
            continue
        season_dir = show / f"Season {season:02d}"
        if find_episode_file(season_dir, season, episode) is not None:
            # already in the library: the raw copy is redundant
            delete_path(media)
            continue
        season_dir.mkdir(parents=True, exist_ok=True)
        dst = season_dir / f"{show_title} - S{season:02d}E{episode:02d}{media.suffix.lower()}"
        try:
            final = import_file(media, dst, mode=mode)
        except OSError:
            unplaced += 1
            continue
        import_subtitles(raw, final, only=_episode_sub_filter(raw, season, episode))
    return unplaced


def cleanup_duplicate_folders(library_root: Path, *, mode: str = "move") -> int:
    """Collapse raw release folders into one clean folder per title (R2.3).

    Raw torrent folders left next to their imported `<Title> (<Year>)` twins are
    verified (media and subtitles imported first) and then deleted, so the
    library holds a single copy per movie/episode. Returns folders removed.
    """
    root = Path(library_root)
    removed = _cleanup_movie_folders(root / "movies", root, mode=mode)
    removed += _cleanup_tv_folders(root / "tv-shows", root, mode=mode)
    return removed


def _cleanup_movie_folders(movies: Path, library_root: Path, *, mode: str) -> int:
    if not movies.is_dir():
        return 0
    folders = [
        p for p in sorted(movies.iterdir()) if p.is_dir() and not p.name.startswith(".")
    ]
    clean = [p for p in folders if is_clean_folder_name(p.name)]
    removed = 0
    for raw in folders:
        if is_clean_folder_name(raw.name) or not looks_like_raw_release(raw.name):
            continue
        title, year = parse_raw_release_name(raw.name)
        if not title or title == "Unknown":
            continue
        target = _clean_folder_match(title, year, clean)
        if target is None:
            final = import_movie(raw, library_root, title, year, mode=mode)
            if final is None:
                continue
            leftovers = [f for f in media_files(raw) if f.exists()]
            if leftovers:
                # Never destroy media that did not make it into the library.
                continue
            target = final.parent
            clean.append(target)
        else:
            _verify_clean_movie(target, raw, mode=mode)
        if delete_path(raw):
            removed += 1
    return removed


def _cleanup_tv_folders(tv: Path, library_root: Path, *, mode: str) -> int:
    if not tv.is_dir():
        return 0
    folders = [
        p for p in sorted(tv.iterdir()) if p.is_dir() and not p.name.startswith(".")
    ]
    shows = [p for p in folders if not looks_like_raw_release(p.name)]
    removed = 0
    for raw in folders:
        if not looks_like_raw_release(raw.name):
            continue
        title, year = parse_raw_release_name(raw.name)
        if not title or title == "Unknown":
            continue
        show = _clean_folder_match(title, year, shows)
        if show is None:
            show = tv / (f"{sanitize_name(title)} ({year})" if year else sanitize_name(title))
            show.mkdir(parents=True, exist_ok=True)
            shows.append(show)
        unplaced = _import_missing_episodes(raw, show, library_root, mode=mode)
        if unplaced:
            continue
        if delete_path(raw):
            removed += 1
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
