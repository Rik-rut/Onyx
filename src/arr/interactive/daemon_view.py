from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from rich.panel import Panel

from arr.interactive.ui import (
    console,
    print_header,
    prompt_text,
)
from arr.transmission.process import (
    Daemon,
    RpcClient,
    find_daemon,
    find_remote,
    find_stale_lock,
    port_in_use,
)

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_daemon(cfg: Config, c: Console | None = None) -> None:
    """Interactive Transmission Daemon status, diagnostics, and management."""
    target = c or console

    while True:
        print_header("Transmission Daemon Status", "Process lifecycle & RPC connectivity", target)

        host = str(cfg.get("transmission_rpc_host", "127.0.0.1"))
        port = int(cfg.get("transmission_rpc_port", 9091))
        download_dir = str(cfg.get("transmission_download_dir", "downloads"))

        # Test RPC connection
        connected = False
        torrents_count = 0
        error_msg = ""
        try:
            rpc = RpcClient(
                host,
                port,
                str(cfg.get("transmission_rpc_user", "") or ""),
                str(cfg.get("transmission_rpc_pass", "") or ""),
            )
            torrents = asyncio.run(rpc.list_torrents())
            connected = True
            torrents_count = len(torrents)
        except Exception as e:
            connected = False
            error_msg = str(e)

        daemon_bin = find_daemon()
        remote_bin = None
        try:
            remote_bin = find_remote(str(cfg.get("transmission_remote", "") or ""))
        except Exception:
            remote_bin = None

        in_use = port_in_use(port)
        stale_lock = find_stale_lock()

        if connected:
            info = (
                f"[bold green]Status: CONNECTED & RUNNING[/bold green]\n"
                f"[cyan]RPC URL:[/cyan] http://{host}:{port}/transmission/rpc\n"
                f"[cyan]Active / Total Torrents:[/cyan] {torrents_count}\n"
                f"[cyan]Download Directory:[/cyan] {download_dir}\n"
                f"[cyan]Daemon Binary:[/cyan] {daemon_bin or 'External / Remote'}\n"
                f"[cyan]Remote Binary:[/cyan] {remote_bin or 'Not found'}"
            )
            target.print(Panel(info, title="Transmission Daemon Online", border_style="green"))
        else:
            diag_lines = [
                "[bold red]Status: UNREACHABLE / OFFLINE[/bold red]",
                f"[cyan]Target RPC:[/cyan] http://{host}:{port}/transmission/rpc",
                f"[cyan]Port {port} in use:[/cyan] {'Yes' if in_use else 'No'}",
                (
                    f"[cyan]transmission-daemon binary:[/cyan] "
                    f"{daemon_bin or '[red]NOT FOUND on PATH[/red]'}"
                ),
                (
                    f"[cyan]transmission-remote binary:[/cyan] "
                    f"{remote_bin or '[yellow]NOT FOUND on PATH[/yellow]'}"
                ),
            ]
            if stale_lock:
                diag_lines.append(
                    f"[yellow]Warning: Stale lock file detected at {stale_lock}[/yellow]"
                )
            if error_msg:
                diag_lines.append(f"[dim]RPC Error: {error_msg}[/dim]")
            diag_lines.append(
                "\n[bold yellow]Remediation Hint:[/bold yellow]\n"
                "Ensure Transmission is installed and transmission-daemon is running.\n"
                "Install Transmission via scoop (`scoop install transmission`), winget, or website."
            )
            target.print(
                Panel(
                    "\n".join(diag_lines),
                    title="Transmission Daemon Offline",
                    border_style="red",
                )
            )

        target.print("\n[bold]Options:[/bold]")
        target.print("  [1] Refresh Status")
        if not connected and daemon_bin:
            target.print("  [2] Start Transmission Daemon Process")
        target.print("  [b] Back to Main Menu")

        choice = prompt_text("Choose action", default="1", allow_back=True, c=target)
        if not choice or choice.lower() in ("b", "back"):
            return

        if choice == "1":
            continue
        elif choice == "2" and not connected and daemon_bin:
            target.print(f"[cyan]Starting transmission-daemon on port {port}...[/cyan]")
            try:
                daemon_proc = Daemon(download_dir=download_dir, port=port)
                daemon_proc.start()
                time.sleep(2)
                target.print("[bold green]Started daemon. Refreshing status...[/bold green]")
            except Exception as e:
                target.print(f"[bold red]Failed to start daemon: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)
        else:
            target.print(f"[red]Unknown choice '{choice}'.[/red]")
