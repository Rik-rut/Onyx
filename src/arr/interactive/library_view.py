from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from arr.importer.layout import MEDIA_EXTS, media_files
from arr.interactive.ui import (
    console,
    print_header,
    prompt_text,
)

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def reveal_in_file_manager(path: Path) -> bool:
    """Open a directory or file in the operating system's default file manager."""
    target_path = path if path.is_dir() else path.parent
    if not target_path.exists():
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(target_path))  # type: ignore[attr-defined]
            return True
        elif sys.platform == "darwin":
            subprocess.run(["open", str(target_path)], check=True)
            return True
        else:
            subprocess.run(["xdg-open", str(target_path)], check=True)
            return True
    except Exception:
        return False


def _excluded_content_paths(cfg: Config | None) -> list[Path]:
    """Resolve raw torrent content paths recorded in the downloads DB.

    With hardlink imports the original torrent payload remains on disk (so
    seeding can continue) but shares the same data as the clean library copy.
    Hiding these from the library view avoids showing the same title twice.
    """
    if cfg is None:
        return []
    try:
        from arr.pipeline import _db

        db = _db(cfg)
    except Exception:
        return []
    out: list[Path] = []
    try:
        for rec in db.list_downloads():
            cp = rec.get("content_path")
            dp = rec.get("destination_path")
            # Only hide a raw folder when a separate imported copy exists.
            # Skipped/in-place downloads (no distinct destination) keep their
            # only visible copy.
            if not cp or not dp:
                continue
            try:
                cp_path = Path(str(cp)).resolve()
                dp_path = Path(str(dp)).resolve()
            except OSError:
                cp_path = Path(str(cp))
                dp_path = Path(str(dp))
            if cp_path == dp_path or cp_path in dp_path.parents:
                continue
            out.append(cp_path)
    except Exception:
        pass
    finally:
        try:
            db.close()
        except Exception:
            pass
    return out


def _is_raw_download(entry: Path, excluded: list[Path]) -> bool:
    """True when a library entry is a raw torrent payload folder/file."""
    if entry.name == ".incomplete":
        return True
    if not excluded:
        return False
    try:
        resolved = entry.resolve()
    except OSError:
        resolved = entry
    for cp in excluded:
        if resolved == cp:
            return True
        if cp in resolved.parents:
            return True
        if entry.is_dir() and cp.parent == resolved:
            return True
    return False


def get_library_movies(movies_dir: Path, cfg: Config | None = None) -> list[dict]:
    """Scan movies directory and return summary dicts."""
    movies: list[dict] = []
    if not movies_dir.exists():
        return movies

    excluded = _excluded_content_paths(cfg)
    for entry in sorted(movies_dir.iterdir()):
        if _is_raw_download(entry, excluded):
            continue
        if entry.is_dir():
            files = [p for p in entry.rglob("*") if p.is_file() and p.suffix.lower() in MEDIA_EXTS]
            if files:
                main_file = max(files, key=lambda p: p.stat().st_size)
                size_mb = sum(p.stat().st_size for p in files) / (1024 * 1024)
                movies.append({
                    "title": entry.name,
                    "path": entry,
                    "file_count": len(files),
                    "size_mb": size_mb,
                    "primary_ext": main_file.suffix.lower(),
                })
        elif entry.is_file() and entry.suffix.lower() in MEDIA_EXTS:
            size_mb = entry.stat().st_size / (1024 * 1024)
            movies.append({
                "title": entry.stem,
                "path": entry,
                "file_count": 1,
                "size_mb": size_mb,
                "primary_ext": entry.suffix.lower(),
            })
    return movies


def get_library_shows(tv_dir: Path, cfg: Config) -> list[dict]:
    """Scan TV shows directory and return show summaries with episode counts and missing status."""
    shows: list[dict] = []
    if not tv_dir.exists():
        return shows

    from arr.pipeline import _db

    db = None
    try:
        db = _db(cfg)
    except Exception:
        db = None

    excluded = _excluded_content_paths(cfg)
    for entry in sorted(tv_dir.iterdir()):
        if not entry.is_dir():
            continue
        if _is_raw_download(entry, excluded):
            continue

        files = media_files(entry)
        seasons = sorted({p.parent.name for p in files if "season" in p.parent.name.lower()})

        # Match with DB monitored series if exists
        monitored_eps: set[str] = set()
        if db is not None:
            try:
                clean_title = re.sub(r"\s*\(\d{4}\)", "", entry.name).strip().lower()
                for s in db.list_monitored():
                    if s.get("title", "").strip().lower() == clean_title:
                        for ep in db.episodes_for_series(s["series_id"]):
                            if ep.get("monitored", True):
                                monitored_eps.add(f"s{ep['season']:02d}e{ep['episode']:02d}")
                        break
            except Exception:
                pass

        present_eps: set[str] = set()
        for f in files:
            m = re.search(r"s(\d{1,2})e(\d{1,2})", f.name, re.IGNORECASE)
            if m:
                present_eps.add(f"s{int(m.group(1)):02d}e{int(m.group(2)):02d}")

        missing = sorted(monitored_eps - present_eps) if monitored_eps else []

        shows.append({
            "title": entry.name,
            "path": entry,
            "seasons_count": len(seasons) if seasons else (1 if files else 0),
            "episodes_count": len(files),
            "monitored_count": len(monitored_eps),
            "missing": missing,
        })

    if db is not None:
        db.close()
    return shows


def interactive_library(cfg: Config, c: Console | None = None) -> None:
    """Browse local media library for movies and TV shows."""
    target = c or console
    lib_root = Path(str(cfg.get("library_root", "downloads"))).resolve()
    movies_dir = lib_root / "movies"
    tv_dir = lib_root / "tv-shows"

    while True:
        print_header("Media Library Browser", f"Storage root: {lib_root}", target)

        movies = get_library_movies(movies_dir, cfg)
        shows = get_library_shows(tv_dir, cfg)

        target.print("[bold]Library Overview:[/bold]")
        target.print(f"  [1] Movies: [cyan]{len(movies)}[/cyan] titles")
        target.print(f"  [2] TV Shows: [cyan]{len(shows)}[/cyan] series")
        target.print("  [o] Open Root Library in File Explorer")
        target.print("  [b] Back to Main Menu")

        choice = prompt_text("Select library section", default="b", allow_back=True, c=target)
        if not choice or choice.lower() in ("b", "back"):
            return

        choice_clean = choice.strip().lower()
        if choice_clean == "1":
            _browse_movies(movies, target)
        elif choice_clean == "2":
            _browse_shows(shows, target)
        elif choice_clean == "o":
            if reveal_in_file_manager(lib_root):
                target.print("[green]Opened library folder in file explorer.[/green]")
            else:
                target.print("[yellow]Could not open library folder.[/yellow]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)
        else:
            target.print(f"[red]Unknown choice '{choice}'.[/red]")


def _browse_movies(movies: list[dict], target: Console) -> None:
    while True:
        print_header("Library Movies", f"{len(movies)} movies found on disk", target)
        if not movies:
            target.print("[yellow]No movies found in downloads/movies.[/yellow]")
            prompt_text("Press Enter to go back", allow_back=False, c=target)
            return

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Title", style="bold cyan")
        table.add_column("Size", style="green", width=12)
        table.add_column("Format", style="yellow", width=8)

        for i, m in enumerate(movies):
            size_str = (
                f"{m['size_mb']/1024:.1f} GB" if m["size_mb"] >= 1024 else f"{m['size_mb']:.0f} MB"
            )
            table.add_row(str(i), m["title"], size_str, m["primary_ext"])

        target.print(table)
        target.print("\n[bold]Options:[/bold] Enter movie # to inspect / open, or 'b' to go back")

        sel = prompt_text("Select movie", default="b", allow_back=True, c=target)
        if not sel or sel.lower() in ("b", "back"):
            return

        if sel.isdigit() and 0 <= int(sel) < len(movies):
            m = movies[int(sel)]
            info = (
                f"[bold white]{m['title']}[/bold white]\n"
                f"Path: {m['path']}\n"
                f"Size: {m['size_mb']/1024:.2f} GB\n"
                f"Files: {m['file_count']}"
            )
            target.print(Panel(info, title="Movie Details", border_style="cyan"))
            action = prompt_text(
                "Options: [o] Open in File Manager  [b] Back", default="o", c=target
            )
            if (action or "").strip().lower() == "o":
                reveal_in_file_manager(m["path"])
                target.print("[green]Opened folder in file explorer.[/green]")
                prompt_text("Press Enter to continue", allow_back=False, c=target)
        else:
            target.print("[red]Invalid selection.[/red]")


def _browse_shows(shows: list[dict], target: Console) -> None:
    while True:
        print_header("Library TV Shows", f"{len(shows)} TV shows found on disk", target)
        if not shows:
            target.print("[yellow]No TV series found in downloads/tv-shows.[/yellow]")
            prompt_text("Press Enter to go back", allow_back=False, c=target)
            return

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Series Title", style="bold cyan")
        table.add_column("Seasons", style="white", width=9)
        table.add_column("Episodes", style="green", width=10)
        table.add_column("Status / Missing", style="yellow")

        for i, s in enumerate(shows):
            if s["missing"]:
                missing_str = f"[bold red]{len(s['missing'])} missing[/bold red]"
            elif s["monitored_count"] > 0:
                missing_str = "[bold green]Complete[/bold green]"
            else:
                missing_str = "[dim]Unmonitored[/dim]"

            table.add_row(
                str(i),
                s["title"],
                str(s["seasons_count"]),
                str(s["episodes_count"]),
                missing_str,
            )

        target.print(table)
        target.print("\n[bold]Options:[/bold] Enter show # to inspect / open, or 'b' to go back")

        sel = prompt_text("Select TV series", default="b", allow_back=True, c=target)
        if not sel or sel.lower() in ("b", "back"):
            return

        if sel.isdigit() and 0 <= int(sel) < len(shows):
            s = shows[int(sel)]
            missing_detail = (
                f"\nMissing: {', '.join(s['missing'][:10])}" if s["missing"] else ""
            )
            info = (
                f"[bold white]{s['title']}[/bold white]\n"
                f"Path: {s['path']}\n"
                f"Seasons: {s['seasons_count']} | Episodes Present: {s['episodes_count']}"
                f"{missing_detail}"
            )
            target.print(Panel(info, title="TV Series Details", border_style="cyan"))
            action = prompt_text(
                "Options: [o] Open in File Manager  [b] Back", default="o", c=target
            )
            if (action or "").strip().lower() == "o":
                reveal_in_file_manager(s["path"])
                target.print("[green]Opened folder in file explorer.[/green]")
                prompt_text("Press Enter to continue", allow_back=False, c=target)
        else:
            target.print("[red]Invalid selection.[/red]")
