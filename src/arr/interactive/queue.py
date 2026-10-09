from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from arr.interactive.ui import (
    console,
    print_header,
    prompt_confirm,
    prompt_text,
    render_queue_table,
)
from arr.pipeline import cancel_download, import_download, list_queue
from arr.transmission.process import RpcClient

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_queue(cfg: Config, c: Console | None = None) -> None:
    """Interactive queue management: display status, refresh, cancel, and manual import."""
    target = c or console

    while True:
        print_header(
            "Download Queue & Active Torrents",
            "Live Transmission status & local download state",
            target,
        )

        # 1. Fetch queue records from local DB
        items = list_queue(cfg)

        # 2. Fetch live torrent status from Transmission RPC
        torrents_by_hash: dict[str, dict] = {}
        try:
            rpc = RpcClient(
                str(cfg.get("transmission_rpc_host", "127.0.0.1")),
                int(cfg.get("transmission_rpc_port", 9091)),
                str(cfg.get("transmission_rpc_user", "") or ""),
                str(cfg.get("transmission_rpc_pass", "") or ""),
            )
            raw_torrents = asyncio.run(rpc.list_torrents())
            torrents_by_hash = {
                str(t.get("hashString", "")).lower(): t for t in raw_torrents
            }
        except Exception:
            torrents_by_hash = {}

        if not items:
            target.print("[yellow]No downloads in queue or history.[/yellow]")
        else:
            target.print(render_queue_table(items, torrents_by_hash, target))

        target.print("\n[bold]Queue Actions:[/bold]")
        target.print("  [1] Refresh View")
        target.print("  [2] Cancel a Download")
        target.print("  [3] Manually Import Completed Download")
        target.print("  [b] Back to Main Menu")

        choice = prompt_text("Choose action", default="1", allow_back=True, c=target)
        if not choice or choice.lower() in ("b", "back"):
            return

        if choice == "1":
            continue

        elif choice == "2":
            target.print("\n[bold]Cancel Download[/bold]")
            dl_id = prompt_text("Enter download hash or ID to cancel", allow_back=True, c=target)
            if not dl_id:
                continue
            del_data = prompt_confirm(
                "Also delete downloaded data from disk?", default=False, c=target
            )
            try:
                asyncio.run(cancel_download(dl_id, cfg, delete_data=del_data))
                target.print(f"[bold green]Cancelled download '{dl_id}'.[/bold green]")
            except Exception as e:
                target.print(f"[bold red]Failed to cancel download: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "3":
            target.print("\n[bold]Manual Import[/bold]")
            dl_id = prompt_text("Enter download hash or ID to import", allow_back=True, c=target)
            if not dl_id:
                continue
            overwrite = prompt_confirm(
                "Overwrite existing files if already present?", default=False, c=target
            )
            try:
                asyncio.run(import_download(dl_id, cfg, overwrite=overwrite))
                target.print(f"[bold green]Import complete for '{dl_id}'.[/bold green]")
            except Exception as e:
                target.print(f"[bold red]Import failed: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        else:
            target.print(f"[red]Unknown choice '{choice}'.[/red]")
