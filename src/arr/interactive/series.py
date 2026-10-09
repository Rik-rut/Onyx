from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from arr.interactive.ui import (
    console,
    print_header,
    prompt_confirm,
    prompt_text,
    render_series_table,
)
from arr.pipeline import series_add, series_check, series_list, series_remove

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_series(cfg: Config, c: Console | None = None) -> None:
    """Interactive series monitoring management: list, add, check, and remove."""
    target = c or console

    while True:
        print_header(
            "Manage Monitored Series",
            "Automatic episode tracking & background downloading",
            target,
        )

        # 1. Fetch monitored series list
        series_items = series_list(cfg)
        if not series_items:
            target.print("[yellow]No series currently monitored.[/yellow]")
        else:
            target.print(render_series_table(series_items, target))

        target.print("\n[bold]Series Actions:[/bold]")
        target.print("  [1] Add New Series to Monitor")
        target.print("  [2] Force Check Series for Airing Episodes")
        target.print("  [3] Remove Series from Monitoring")
        target.print("  [4] Refresh List")
        target.print("  [b] Back to Main Menu")

        choice = prompt_text("Choose action", default="4", allow_back=True, c=target)
        if not choice or choice.lower() in ("b", "back"):
            return

        if choice == "1":
            target.print("\n[bold]Add New Series[/bold]")
            query = prompt_text("Enter TV show title to monitor", allow_back=True, c=target)
            if not query:
                continue
            target.print(f"[cyan]Adding '{query}' to monitoring and checking episodes...[/cyan]")
            try:
                asyncio.run(series_add(query, cfg))
                target.print(f"[bold green]Added and scheduled '{query}'.[/bold green]")
            except SystemExit as e:
                if e.code == 3:
                    target.print(f"[yellow]No series found matching '{query}'.[/yellow]")
                elif e.code == 4:
                    target.print("[red]Metadata source unavailable.[/red]")
                else:
                    target.print(f"[red]Failed with exit code {e.code}.[/red]")
            except Exception as e:
                target.print(f"[bold red]Failed to add series: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "2":
            target.print("\n[bold]Force Check Series[/bold]")
            sid_input = prompt_text("Enter Series ID to check", allow_back=True, c=target)
            if not sid_input or not sid_input.isdigit():
                continue
            sid = int(sid_input)
            target.print(f"[cyan]Checking for newly aired episodes for series ID {sid}...[/cyan]")
            try:
                asyncio.run(series_check(sid, cfg))
                target.print(f"[bold green]Check completed for series ID {sid}.[/bold green]")
            except SystemExit as e:
                if e.code == 3:
                    target.print("[yellow]No such series found in database.[/yellow]")
                elif e.code == 4:
                    target.print("[red]TVMaze lookup failed.[/red]")
            except Exception as e:
                target.print(f"[bold red]Check failed: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "3":
            target.print("\n[bold]Remove Series[/bold]")
            sid_input = prompt_text("Enter Series ID to remove", allow_back=True, c=target)
            if not sid_input or not sid_input.isdigit():
                continue
            sid = int(sid_input)
            del_files = prompt_confirm(
                "Also delete downloaded media files from library?", default=False, c=target
            )
            try:
                series_remove(sid, cfg, delete_files=del_files)
                target.print(f"[bold green]Removed series ID {sid}.[/bold green]")
            except SystemExit as e:
                if e.code == 3:
                    target.print("[yellow]No such series found in database.[/yellow]")
            except Exception as e:
                target.print(f"[bold red]Failed to remove series: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "4":
            continue

        else:
            target.print(f"[red]Unknown choice '{choice}'.[/red]")
