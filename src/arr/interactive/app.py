from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel

from arr.interactive.config_view import interactive_config
from arr.interactive.daemon_view import interactive_daemon
from arr.interactive.library_view import interactive_library
from arr.interactive.movie import interactive_movie
from arr.interactive.queue import interactive_queue
from arr.interactive.series import interactive_series
from arr.interactive.tv import interactive_tv
from arr.interactive.ui import (
    console,
    print_banner,
    prompt_confirm,
    prompt_text,
)

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def run_interactive(cfg: Config, c: Console | None = None) -> int:
    """Run the main interactive CLI terminal application."""
    target = c or console

    port = int(cfg.get("transmission_rpc_port", 9091))
    from arr.transmission.process import port_in_use

    was_running = port_in_use(port, timeout=0.1)
    daemon_proc = None
    if not was_running:
        try:
            from arr.transmission.process import ensure_daemon

            daemon_proc = ensure_daemon(cfg)
        except Exception:
            pass

    def _cleanup_exit(interrupted: bool = False) -> int:
        if daemon_proc is not None:
            keep = prompt_confirm(
                "Keep Transmission running in background for seeding?",
                default=True,
                c=target,
            )
            if not keep:
                try:
                    daemon_proc.stop()
                    target.print("[dim]Stopped Transmission daemon process.[/dim]")
                except Exception:
                    pass
        if interrupted:
            target.print("\n[yellow]Exiting Onyx interactive mode. Goodbye![/yellow]")
        else:
            target.print("[yellow]Goodbye![/yellow]")
        return 0

    while True:
        try:
            print_banner(target)

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
                "[bold white][7][/bold white] Browse Local Media Library\n"
                "[bold white][8][/bold white] Launch Web Dashboard\n"
                "[bold white][d][/bold white] Direct Magnet / Torrent Download\n"
                "[bold white][0][/bold white] Exit"
            )
            target.print(Panel(menu_text, title="Main Menu", border_style="cyan", padding=(1, 2)))

            choice = prompt_text("Select an option [0-8, d]", allow_back=False, c=target)
            if choice is None:
                return _cleanup_exit(interrupted=True)

            choice_clean = choice.strip()
            if choice_clean == "0" or choice_clean.lower() in ("exit", "quit", "q"):
                return _cleanup_exit()

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

            elif choice_clean in ("7", "l", "library"):
                try:
                    interactive_library(cfg, target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")

            elif choice_clean.lower() in ("8", "w", "web"):
                try:
                    import webbrowser

                    import uvicorn

                    from arr.web.app import create_app

                    host = "127.0.0.1"
                    port_val = 3698
                    web_url = f"http://{host}:{port_val}"
                    target.print(
                        f"\n[bold green]Starting Web Dashboard at {web_url}...[/bold green]"
                    )
                    target.print("[dim]Press Ctrl+C to return to main menu.[/dim]")
                    try:
                        webbrowser.open(web_url)
                    except Exception:
                        pass
                    web_app = create_app(cfg)
                    uvicorn.run(web_app, host=host, port=port_val, log_level="warning")
                except KeyboardInterrupt:
                    target.print("\n[yellow]Web Dashboard stopped.[/yellow]")

            elif choice_clean.lower() in ("d", "magnet", "direct"):
                try:
                    target.print("\n[bold]Direct Magnet / .torrent Ingestion[/bold]")
                    uri_val = prompt_text(
                        "Paste Magnet URI or .torrent file path",
                        allow_back=True,
                        c=target,
                    )
                    if uri_val:
                        import asyncio

                        from arr.pipeline import download_magnet

                        asyncio.run(download_magnet(uri_val, cfg))
                        prompt_text("Press Enter to continue", allow_back=False, c=target)
                except KeyboardInterrupt:
                    target.print("\n[yellow]Operation cancelled.[/yellow]")
                except Exception as e:
                    target.print(f"[bold red]Download failed: {e}[/bold red]")
                    prompt_text("Press Enter to continue", allow_back=False, c=target)

            else:
                target.print(
                    f"[red]Invalid selection '{choice_clean}'. Please choose [0-8, d].[/red]"
                )

        except KeyboardInterrupt:
            return _cleanup_exit(interrupted=True)
