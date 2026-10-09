from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from arr.config.settings import Config
    from arr.core.models import Release

console = Console()


def format_size(size_bytes: int | float | None) -> str:
    """Format bytes into human-readable size string (e.g. 2.4 GB)."""
    if size_bytes is None or size_bytes < 0:
        return "--"
    b = float(size_bytes)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if b < 1024.0 or unit == "TB":
            return f"{b:.1f} {unit}" if unit in ("GB", "TB", "MB") else f"{int(b)} {unit}"
        b /= 1024.0
    return f"{b:.1f} GB"


def format_speed(rate_bytes_per_sec: int | float | None) -> str:
    """Format download rate in bytes/sec to human readable (e.g. 1.5 MB/s)."""
    if rate_bytes_per_sec is None or rate_bytes_per_sec <= 0:
        return "0 B/s"
    b = float(rate_bytes_per_sec)
    for unit in ["B/s", "KB/s", "MB/s", "GB/s"]:
        if b < 1024.0 or unit == "GB/s":
            return f"{b:.1f} {unit}"
        b /= 1024.0
    return f"{b:.1f} MB/s"


def format_eta(seconds: int | float | None) -> str:
    """Format ETA in seconds into human readable duration (e.g. 5m 30s)."""
    if seconds is None or seconds < 0:
        return "--"
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    m, s = divmod(s, 60)
    if m < 60:
        return f"{m}m {s:02d}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m:02d}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def print_header(title: str, subtitle: str | None = None, c: Console | None = None) -> None:
    """Print a styled section header panel."""
    target = c or console
    content = f"[bold cyan]{title}[/bold cyan]"
    if subtitle:
        content += f"\n[dim]{subtitle}[/dim]"
    target.print(Panel(content, border_style="cyan", padding=(0, 2)))


def print_banner(c: Console | None = None) -> None:
    """Print the application startup banner."""
    target = c or console
    banner_text = (
        "[bold cyan]ARR — Shows & Movies Downloader[/bold cyan]\n"
        "[dim]Autonomous BitTorrent Search, Quality Ranking & Media Library Manager[/dim]"
    )
    target.print(Panel(banner_text, border_style="blue", padding=(0, 2)))


def render_releases_table(releases: list[Release], c: Console | None = None) -> Table:
    """Render ranked releases into a styled Rich Table."""
    table = Table(
        title="Search Results (Ranked by Quality & Seeders)",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Release Title", style="bold white", no_wrap=False)
    table.add_column("Res", justify="center", style="cyan", width=8)
    table.add_column("Source", justify="center", style="blue", width=9)
    table.add_column("Codec", justify="center", style="yellow", width=8)
    table.add_column("Size", justify="right", style="green", width=10)
    table.add_column("Seeds", justify="right", style="bold green", width=7)
    table.add_column("Peers", justify="right", style="dim", width=7)
    table.add_column("Indexer", justify="center", style="magenta", width=9)

    for i, r in enumerate(releases):
        table.add_row(
            str(i),
            r.title,
            r.resolution or "--",
            r.source or "--",
            r.codec or "--",
            format_size(r.size_bytes),
            str(r.seeds),
            str(r.peers),
            r.indexer or "--",
        )
    return table


def make_progress_bar(pct: float, width: int = 10) -> str:
    """Render a visual Unicode progress bar string, e.g. [████████░░] 78.4%."""
    pct_clamped = max(0.0, min(100.0, float(pct)))
    filled = int(round((pct_clamped / 100.0) * width))
    filled = max(0, min(width, filled))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    return f"[{bar}] {pct_clamped:.1f}%"


def render_queue_table(
    items: list[dict],
    torrents_by_hash: dict[str, dict] | None = None,
    c: Console | None = None,
) -> Table:
    """Render download queue and active torrents into a styled Rich Table."""
    table = Table(
        title="Download Queue & Active Torrents",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Hash", style="dim", width=10)
    table.add_column("Title", style="bold white", no_wrap=False)
    table.add_column("Type", justify="center", style="cyan", width=7)
    table.add_column("State", justify="center", width=12)
    table.add_column("Progress", justify="left", width=20)
    table.add_column("Down Speed", justify="right", width=12)
    table.add_column("ETA", justify="right", width=10)

    by_hash = torrents_by_hash or {}
    for item in items:
        h = str(item.get("infohash", ""))
        short_h = h[:8]
        title = item.get("title") or "Unknown"
        media_type = (item.get("media_type") or "tv").upper()
        state = item.get("state") or "unknown"
        t = by_hash.get(h.lower())

        if state == "completed":
            state_str = "[green]completed[/green]"
        elif state == "downloading":
            state_str = "[bold blue]downloading[/bold blue]"
        elif state == "imported":
            state_str = "[bold green]imported[/bold green]"
        elif state == "queued":
            state_str = "[yellow]queued[/yellow]"
        elif state == "skipped":
            state_str = "[dim]cancelled[/dim]"
        elif state == "failed":
            state_str = "[red]failed[/red]"
        else:
            state_str = f"[cyan]{state}[/cyan]"

        if t is not None:
            pct = float(t.get("percentDone", 0.0)) * 100
            bar = make_progress_bar(pct)
            progress_str = f"[cyan]{bar}[/cyan]"
            speed_str = format_speed(t.get("rateDownload", 0))
            eta_str = format_eta(t.get("eta"))
        elif state in ("imported", "completed"):
            progress_str = f"[green]{make_progress_bar(100.0)}[/green]"
            speed_str = "--"
            eta_str = "--"
        elif state == "queued":
            progress_str = f"[yellow]{make_progress_bar(0.0)}[/yellow]"
            speed_str = "--"
            eta_str = "--"
        else:
            progress_str = "--"
            speed_str = "--"
            eta_str = "--"

        table.add_row(short_h, title, media_type, state_str, progress_str, speed_str, eta_str)
    return table


def render_series_table(series_list: list[dict], c: Console | None = None) -> Table:
    """Render monitored series list into a styled Rich Table."""
    table = Table(title="Monitored TV Series", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="dim", justify="right", width=5)
    table.add_column("Title", style="bold white")
    table.add_column("Status", justify="center", style="cyan", width=16)
    table.add_column("Imported", justify="right", style="green", width=10)
    table.add_column("Pending", justify="right", style="yellow", width=9)
    table.add_column("Missing", justify="right", style="red", width=9)
    table.add_column("Last Checked", justify="center", style="dim", width=18)

    for s in series_list:
        table.add_row(
            str(s.get("id", "")),
            s.get("title") or "Unknown",
            s.get("status") or "--",
            str(s.get("imported_episodes", 0)),
            str(s.get("pending_episodes", 0)),
            str(s.get("missing_episodes", 0)),
            str(s.get("last_checked_at") or "never"),
        )
    return table


def prompt_text(
    message: str,
    default: str | None = None,
    allow_back: bool = True,
    c: Console | None = None,
) -> str | None:
    """Prompt for free-form text input with back support."""
    target = c or console
    suffix = " [b=back]: " if allow_back else ": "
    try:
        val = target.input(f"[bold]{message}[/bold]{suffix}").strip()
    except (KeyboardInterrupt, EOFError):
        return None
    if not val:
        if default is not None:
            return default
        return ""
    if allow_back and val.lower() in ("b", "back"):
        return None
    return val


def prompt_choice(
    message: str,
    choices: list[str],
    default: str | None = None,
    c: Console | None = None,
) -> str:
    """Prompt for a choice from a list of options with automatic validation."""
    target = c or console
    choice_list_str = "/".join(choices)
    while True:
        try:
            val = target.input(f"[bold]{message}[/bold] ({choice_list_str}): ").strip()
        except (KeyboardInterrupt, EOFError):
            return default if default is not None else choices[0]
        if not val and default is not None:
            return default
        for ch in choices:
            if val.lower() == ch.lower():
                return ch
        target.print(f"[red]Invalid choice '{val}'. Please choose from {choice_list_str}[/red]")


def prompt_confirm(message: str, default: bool = False, c: Console | None = None) -> bool:
    """Prompt for yes/no confirmation."""
    target = c or console
    hint = " [Y/n]: " if default else " [y/N]: "
    try:
        val = target.input(f"[bold]{message}[/bold]{hint}").strip().lower()
    except (KeyboardInterrupt, EOFError):
        return False
    if not val:
        return default
    return val in ("y", "yes")


def render_matches_table(
    matches: list[dict],
    title_type: str = "TV Show",
    c: Console | None = None,
) -> Table:
    """Render close matching search results into a styled Rich Table."""
    table = Table(
        title=f"Matching {title_type}s Found",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Title", style="bold white", no_wrap=False)
    table.add_column("Year", justify="center", style="cyan", width=8)
    table.add_column("Status / Type", justify="center", width=18)
    table.add_column("Network / Genres / Details", style="dim", no_wrap=False)

    for i, m in enumerate(matches):
        idx_str = str(i)
        title = m.get("title") or m.get("name") or "Unknown"
        year = str(m.get("year") or "--")
        status = m.get("status") or m.get("type") or "--"
        if status in ("Ended", "Completed"):
            status_str = f"[green]{status}[/green]"
        elif status in ("Running", "Ongoing", "Returning Series"):
            status_str = f"[yellow]{status}[/yellow]"
        else:
            status_str = f"[cyan]{status}[/cyan]"

        details_parts = []
        if m.get("network"):
            details_parts.append(str(m["network"]))
        if m.get("genres"):
            genres = m["genres"]
            if isinstance(genres, list):
                details_parts.append(", ".join(str(g) for g in genres[:3]))
            else:
                details_parts.append(str(genres))
        if m.get("stars"):
            details_parts.append(f"Stars: {m['stars']}")
        details = " | ".join(details_parts) if details_parts else "--"

        table.add_row(idx_str, title, year, status_str, details)

    return table


def render_seasons_table(seasons: list[dict], c: Console | None = None) -> Table:
    """Render seasons overview with status, episode counts, and air dates."""
    table = Table(
        title="Available Seasons & Status",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("Season", style="bold white", width=12)
    table.add_column("Status", justify="center", width=16)
    table.add_column("Episodes", justify="right", style="cyan", width=10)
    table.add_column("Air Dates", justify="center", style="dim", width=26)

    for s in seasons:
        s_num = s.get("season_number", 0)
        status = s.get("status", "Unknown")
        if status == "Completed":
            status_str = "[bold green]Completed[/bold green]"
        elif status == "Ongoing":
            status_str = "[bold yellow]Ongoing[/bold yellow]"
        elif status == "Upcoming":
            status_str = "[bold cyan]Upcoming[/bold cyan]"
        else:
            status_str = f"[dim]{status}[/dim]"

        count = f"{s.get('episode_count', 0)} eps"
        prem = s.get("premiere_date") or "--"
        end = s.get("end_date") or "--"
        if prem != "--" and end != "--" and prem != end:
            dates = f"{prem} to {end}"
        elif prem != "--":
            dates = prem
        else:
            dates = "--"

        table.add_row(f"Season {s_num:02d}", status_str, count, dates)

    return table


def render_episodes_table(episodes: list[Any], c: Console | None = None) -> Table:
    """Render season episodes table."""
    table = Table(
        title="Episodes List",
        show_header=True,
        header_style="bold magenta",
    )
    table.add_column("#", style="dim", justify="right", width=4)
    table.add_column("Episode", justify="center", style="cyan", width=8)
    table.add_column("Title", style="bold white", no_wrap=False)
    table.add_column("Air Date", justify="center", style="dim", width=14)

    for i, ep in enumerate(episodes):
        ep_num = getattr(ep, "episode_number", None)
        if ep_num is None and isinstance(ep, dict):
            ep_num = ep.get("episode_number") or ep.get("number")
        ep_num_val = int(ep_num or (i + 1))

        name = getattr(ep, "name", None)
        if name is None and isinstance(ep, dict):
            name = ep.get("name")
        title = str(name or f"Episode {ep_num_val}")

        air_date = getattr(ep, "air_date", None)
        if air_date is None and isinstance(ep, dict):
            air_date = ep.get("air_date") or ep.get("airdate")
        date_str = str(air_date or "--")

        table.add_row(str(i + 1), f"E{ep_num_val:02d}", title, date_str)

    return table


def parse_episode_selection(text: str, max_ep: int | None = None) -> list[int]:
    """Parse episode selection string into a sorted, unique list of integers.

    Supported syntax:
      - 'all': selects all episodes 1..max_ep (requires max_ep > 0)
      - single: '1', ' 4 ' -> [1], [4]
      - comma-separated: '1, 3, 5' -> [1, 3, 5]
      - range: '1-4' -> [1, 2, 3, 4]
      - combined: '1-3, 5, 8-10' -> [1, 2, 3, 5, 8, 9, 10]
    """
    cleaned = text.strip().lower()
    if not cleaned:
        raise ValueError("Selection cannot be empty")

    if cleaned == "all":
        if not max_ep or max_ep <= 0:
            raise ValueError("Cannot select 'all': maximum episode count unknown")
        return list(range(1, max_ep + 1))

    selected: set[int] = set()
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    if not parts:
        raise ValueError("No valid episode numbers provided")

    for part in parts:
        if "-" in part:
            sub = [s.strip() for s in part.split("-")]
            if len(sub) != 2 or not sub[0].isdigit() or not sub[1].isdigit():
                raise ValueError(f"Invalid range format: '{part}'")
            start, end = int(sub[0]), int(sub[1])
            if start <= 0 or end <= 0:
                raise ValueError("Episode numbers must be greater than 0")
            if start > end:
                raise ValueError(f"Range start ({start}) cannot exceed end ({end})")
            for ep in range(start, end + 1):
                if max_ep and ep > max_ep:
                    raise ValueError(f"Episode {ep} exceeds maximum available ({max_ep})")
                selected.add(ep)
        else:
            if not part.isdigit():
                raise ValueError(f"Invalid episode number: '{part}'")
            ep = int(part)
            if ep <= 0:
                raise ValueError("Episode numbers must be greater than 0")
            if max_ep and ep > max_ep:
                raise ValueError(f"Episode {ep} exceeds maximum available ({max_ep})")
            selected.add(ep)

    return sorted(selected)


def live_monitor_downloads(
    cfg: Config,
    c: Console | None = None,
    single_hash: str | None = None,
    auto_exit_when_done: bool = False,
    max_iterations: int | None = None,
    poll_interval: float = 1.0,
) -> None:
    """Live real-time download tracking with progress bars, transfer speed, and ETA."""
    target = c or console
    import asyncio

    from arr.pipeline import list_queue
    from arr.transmission.process import RpcClient

    print_header(
        "Live Download Monitor",
        "Tracking active torrents in real-time (press 'q', 'b', Enter, or Ctrl+C to return)",
        target,
    )

    rpc = RpcClient(
        str(cfg.get("transmission_rpc_host", "127.0.0.1")),
        int(cfg.get("transmission_rpc_port", 9091)),
        str(cfg.get("transmission_rpc_user", "") or ""),
        str(cfg.get("transmission_rpc_pass", "") or ""),
    )

    if not sys.stdin.isatty() and max_iterations is None:
        max_iterations = 1

    iterations = 0
    try:
        from rich.live import Live

        with Live(console=target, refresh_per_second=2, transient=False) as live:
            while True:
                iterations += 1
                try:
                    torrents = asyncio.run(rpc.list_torrents())
                except Exception:
                    torrents = []
                    if not sys.stdin.isatty():
                        break

                db_items = list_queue(cfg)
                torrents_by_hash = {
                    str(t.get("hashString", "")).lower(): t for t in torrents
                }

                if single_hash:
                    t = torrents_by_hash.get(single_hash.lower())
                    if t:
                        pct = float(t.get("percentDone", 0.0)) * 100
                        speed = format_speed(t.get("rateDownload", 0))
                        eta = format_eta(t.get("eta"))
                        status = t.get("status", "unknown")
                        bar = make_progress_bar(pct, width=20)
                        title = t.get("name") or single_hash[:10]

                        content = (
                            f"[bold white]{title}[/bold white]\n\n"
                            f"Progress:  {bar}\n"
                            f"Speed:     [cyan]{speed}[/cyan]   ETA: [yellow]{eta}[/yellow]\n"
                            f"Status:    [magenta]{status}[/magenta]"
                        )
                        live.update(
                            Panel(content, title="Live Torrent Progress", border_style="cyan")
                        )

                        if auto_exit_when_done and pct >= 100.0:
                            target.print(
                                f"\n[bold green]Download complete: {title}![/bold green]"
                            )
                            break
                    else:
                        live.update(
                            Panel(
                                f"Waiting for torrent [cyan]{single_hash[:10]}[/cyan] "
                                "to appear in Transmission...",
                                title="Live Torrent Progress",
                                border_style="yellow",
                            )
                        )
                else:
                    table = render_queue_table(db_items, torrents_by_hash, target)
                    live.update(table)

                if max_iterations is not None and iterations >= max_iterations:
                    break

                if sys.platform == "win32":
                    try:
                        import msvcrt

                        if msvcrt.kbhit():
                            msvcrt.getch()
                            break
                    except Exception:
                        pass

                time.sleep(poll_interval)
    except KeyboardInterrupt:
        target.print("\n[dim]Stopped live monitoring.[/dim]")
    except Exception as e:
        target.print(f"[yellow]Live monitor ended: {e}[/yellow]")

