from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from arr.interactive.ui import (
    console,
    live_monitor_downloads,
    print_header,
    prompt_confirm,
    prompt_text,
    render_queue_table,
)
from arr.pipeline import (
    cancel_download,
    import_download,
    list_queue,
    pause_download,
    resume_download,
    set_download_priority,
)
from arr.transmission.process import RpcClient

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def _resolve_download_id(raw: str, items: list[dict]) -> str:
    cleaned = raw.strip()
    if not cleaned:
        return ""
    if cleaned.isdigit():
        idx = int(cleaned)
        if 0 <= idx < len(items):
            return str(items[idx]["infohash"])
    lower = cleaned.lower()
    for item in items:
        h = str(item.get("infohash", "")).lower()
        if h.startswith(lower):
            return str(item["infohash"])
    return cleaned


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
        target.print("  [4] Live Monitor (Real-time tracking)")
        target.print("  [5] Pause Download")
        target.print("  [6] Resume Download")
        target.print("  [7] Move Queue Priority")
        target.print("  [b] Back to Main Menu")

        choice = prompt_text("Choose action", default="1", allow_back=True, c=target)
        if not choice or choice.lower() in ("b", "back"):
            return

        if choice == "1":
            continue

        elif choice == "4":
            live_monitor_downloads(cfg, target)
            continue

        elif choice == "2":
            target.print("\n[bold]Cancel Download[/bold]")
            prompt_label = (
                f"Enter download index [0-{len(items)-1}] or hash to cancel"
                if items
                else "Enter download hash to cancel"
            )
            dl_id = prompt_text(prompt_label, allow_back=True, c=target)
            if not dl_id:
                continue
            target_id = _resolve_download_id(dl_id, items)
            target.print(
                "[dim]Removing the torrent and deleting its downloaded files "
                "from downloads/.[/dim]"
            )
            try:
                asyncio.run(cancel_download(target_id, cfg))
                target.print(
                    f"[bold green]Cancelled download '{target_id[:8]}' and deleted its files."
                    "[/bold green]"
                )
            except SystemExit as e:
                if e.code == 3:
                    target.print(f"[bold red]Download '{dl_id}' not found.[/bold red]")
                else:
                    target.print(f"[bold red]Cancel failed with exit code {e.code}.[/bold red]")
            except Exception as e:
                target.print(f"[bold red]Failed to cancel download: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "3":
            target.print("\n[bold]Manual Import[/bold]")
            prompt_label = (
                f"Enter download index [0-{len(items)-1}] or hash to import"
                if items
                else "Enter download hash to import"
            )
            dl_id = prompt_text(prompt_label, allow_back=True, c=target)
            if not dl_id:
                continue
            target_id = _resolve_download_id(dl_id, items)
            overwrite = prompt_confirm(
                "Overwrite existing files if already present?", default=False, c=target
            )
            try:
                asyncio.run(import_download(target_id, cfg, overwrite=overwrite))
                target.print(f"[bold green]Import complete for '{target_id[:8]}'.[/bold green]")
            except SystemExit as e:
                if e.code == 3:
                    target.print(f"[bold red]Download '{dl_id}' not found.[/bold red]")
                elif e.code == 1:
                    target.print(
                        f"[bold red]Nothing importable found for '{target_id[:8]}'.[/bold red]"
                    )
                else:
                    target.print(f"[bold red]Import failed with exit code {e.code}.[/bold red]")
            except Exception as e:
                target.print(f"[bold red]Import failed: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "5":
            target.print("\n[bold]Pause Download[/bold]")
            prompt_label = (
                f"Enter download index [0-{len(items)-1}] or hash to pause"
                if items
                else "Enter download hash to pause"
            )
            dl_id = prompt_text(prompt_label, allow_back=True, c=target)
            if not dl_id:
                continue
            target_id = _resolve_download_id(dl_id, items)
            try:
                asyncio.run(pause_download(target_id, cfg))
                target.print(f"[bold green]Paused download '{target_id[:8]}'.[/bold green]")
            except SystemExit as e:
                target.print(f"[bold red]Download '{dl_id}' not found (exit {e.code}).[/bold red]")
            except Exception as e:
                target.print(f"[bold red]Pause failed: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "6":
            target.print("\n[bold]Resume Download[/bold]")
            prompt_label = (
                f"Enter download index [0-{len(items)-1}] or hash to resume"
                if items
                else "Enter download hash to resume"
            )
            dl_id = prompt_text(prompt_label, allow_back=True, c=target)
            if not dl_id:
                continue
            target_id = _resolve_download_id(dl_id, items)
            try:
                asyncio.run(resume_download(target_id, cfg))
                target.print(f"[bold green]Resumed download '{target_id[:8]}'.[/bold green]")
            except SystemExit as e:
                target.print(f"[bold red]Download '{dl_id}' not found (exit {e.code}).[/bold red]")
            except Exception as e:
                target.print(f"[bold red]Resume failed: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        elif choice == "7":
            target.print("\n[bold]Move Queue Priority[/bold]")
            prompt_label = (
                f"Enter download index [0-{len(items)-1}] or hash"
                if items
                else "Enter download hash"
            )
            dl_id = prompt_text(prompt_label, allow_back=True, c=target)
            if not dl_id:
                continue
            target_id = _resolve_download_id(dl_id, items)
            pri = prompt_text(
                "Priority action (top/up/down/bottom/high/low)",
                default="up",
                allow_back=True,
                c=target,
            )
            if not pri:
                continue
            try:
                asyncio.run(set_download_priority(target_id, pri, cfg))
                short_id = target_id[:8]
                target.print(f"[bold green]Set priority '{pri}' for '{short_id}'.[/bold green]")
            except SystemExit as e:
                target.print(f"[bold red]Download '{dl_id}' not found (exit {e.code}).[/bold red]")
            except Exception as e:
                target.print(f"[bold red]Priority update failed: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)

        else:
            target.print(f"[red]Unknown choice '{choice}'.[/red]")
