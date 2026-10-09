from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from arr.config.settings import default_config_path
from arr.interactive.ui import (
    console,
    print_header,
    prompt_text,
)

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_config(cfg: Config, c: Console | None = None) -> None:
    """Interactive configuration viewer."""
    target = c or console

    while True:
        print_header("Configuration & Settings", "Active settings and runtime parameters", target)

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Setting", style="bold cyan", width=30)
        table.add_column("Current Value", style="white")

        table.add_row("Config File Path", str(default_config_path()))
        table.add_row("Download Root", str(cfg.get("download_root", "downloads")))
        table.add_row("Library Root", str(cfg.get("library_root", "downloads")))
        rpc_url = (
            f"http://{cfg.get('transmission_rpc_host', '127.0.0.1')}:"
            f"{cfg.get('transmission_rpc_port', 9091)}/transmission/rpc"
        )
        table.add_row("Transmission RPC", rpc_url)
        table.add_row("Import Mode", str(cfg.get("import_mode", "hardlink")))
        table.add_row("Max Concurrent Downloads", str(cfg.get("max_concurrent_downloads", 3)))
        table.add_row("Prefer Season Packs", str(cfg.get("prefer_season_packs", True)))
        table.add_row("Quality Resolutions", ", ".join(cfg.get("resolutions") or []))
        table.add_row("Min Seeders", str(cfg.get("min_seeders", 1)))
        table.add_row("Seeding Policy", str(cfg.get("seeding_policy", "ratio")))
        table.add_row("Subtitles Enabled", str(cfg.get("subtitles_enabled", True)))
        table.add_row("Subtitle Languages", ", ".join(cfg.get("subtitle_languages") or ["en"]))
        table.add_row("Subtitles Forced Only", str(cfg.get("subtitles_forced_only", False)))

        target.print(table)

        target.print("\n[bold]Options:[/bold]")
        target.print("  [1] View Full Configuration (JSON / Redacted)")
        target.print("  [b] Back to Main Menu")

        choice = prompt_text("Choose action", default="b", allow_back=True, c=target)
        if not choice or choice.lower() in ("b", "back"):
            return

        if choice == "1":
            redacted_data = json.dumps(cfg.redacted(), indent=2)
            target.print(
                Panel(redacted_data, title="Active Configuration (Redacted)", border_style="cyan")
            )
            prompt_text("Press Enter to continue", allow_back=False, c=target)
        else:
            target.print(f"[red]Unknown choice '{choice}'.[/red]")
