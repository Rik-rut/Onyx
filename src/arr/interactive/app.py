from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel

from arr.interactive.config_view import interactive_config
from arr.interactive.daemon_view import interactive_daemon
from arr.interactive.movie import interactive_movie
from arr.interactive.queue import interactive_queue
from arr.interactive.series import interactive_series
from arr.interactive.tv import interactive_tv
from arr.interactive.ui import (
    console,
    print_banner,
    prompt_text,
)

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def run_interactive(cfg: Config, c: Console | None = None) -> int:
    """Run the main interactive CLI terminal application."""
    target = c or console

    # Auto-start or ensure transmission-daemon is running on local machine
    try:
        from arr.transmission.process import ensure_daemon

        ensure_daemon(cfg)
    except Exception:
        pass

    while True:
        try:
            print_banner(target)

            from arr.transmission.process import port_in_use

            port = int(cfg.get("transmission_rpc_port", 9091))
            status_indicator = (
                f"[bold green]● Transmission Online (port {port})[/bold green]"
                if port_in_use(port, timeout=0.1)
                else "[yellow]○ Transmission Offline[/yellow]"
            )

            menu_text = (
                f"{status_indicator}\n\n"
                "[bold white][1][/bold white] Search & Download TV Shows\n"
                "[bold white][2][/bold white] Search & Download Movies\n"
                "[bold white][3][/bold white] Manage Monitored Series\n"
                "[bold white][4][/bold white] Queue & Active Downloads\n"
                "[bold white][5][/bold white] Transmission Daemon Status\n"
                "[bold white][6][/bold white] Configuration & Settings\n"
                "[bold white][0][/bold white] Exit"
            )
            target.print(Panel(menu_text, title="Main Menu", border_style="cyan", padding=(1, 2)))


            choice = prompt_text("Select an option [0-6]", allow_back=False, c=target)
            if choice is None:
                # EOF or Ctrl+C at main prompt
                target.print("\n[yellow]Exiting ARR interactive mode. Goodbye![/yellow]")
                return 0

            choice_clean = choice.strip()
            if choice_clean == "0" or choice_clean.lower() in ("exit", "quit", "q"):
                target.print("[yellow]Goodbye![/yellow]")
                return 0

            if choice_clean == "1":
                try:
                    interactive_tv(cfg, target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")

            elif choice_clean == "2":
                try:
                    interactive_movie(cfg, target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")

            elif choice_clean == "3":
                try:
                    interactive_series(cfg, target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")

            elif choice_clean == "4":
                try:
                    interactive_queue(cfg, target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")

            elif choice_clean == "5":
                try:
                    interactive_daemon(cfg, target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")

            elif choice_clean == "6":
                try:
                    interactive_config(cfg, target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")

            else:
                target.print(f"[red]Invalid selection '{choice_clean}'. Please choose [0-6].[/red]")

        except KeyboardInterrupt:
            target.print("\n[yellow]Exiting ARR interactive mode. Goodbye![/yellow]")
            return 0
