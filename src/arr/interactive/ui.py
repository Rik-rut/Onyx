from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
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
    table.add_column("Progress", justify="right", width=10)
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
            progress_str = f"{pct:.1f}%"
            speed_str = format_speed(t.get("rateDownload", 0))
            eta_str = format_eta(t.get("eta"))
        elif state in ("imported", "completed"):
            progress_str = "100.0%"
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
