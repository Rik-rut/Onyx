from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table

from arr.config.settings import default_config_path, save_config
from arr.interactive.ui import (
    console,
    print_header,
    prompt_confirm,
    prompt_text,
)

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_config(cfg: Config, c: Console | None = None) -> None:
    """Interactive configuration viewer and editor."""
    target = c or console

    while True:
        print_header("Configuration & Settings", "Active settings and runtime parameters", target)

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("#", style="dim", width=4)
        table.add_column("Setting", style="bold cyan", width=28)
        table.add_column("Current Value", style="white")

        table.add_row("-", "Config File Path", str(default_config_path()))
        table.add_row("1", "Download Root", str(cfg.get("download_root", "downloads")))
        table.add_row("2", "Library Root", str(cfg.get("library_root", "downloads")))
        table.add_row("3", "Import Mode", str(cfg.get("import_mode", "hardlink")))
        table.add_row("4", "Max Concurrent Downloads", str(cfg.get("max_concurrent_downloads", 3)))
        table.add_row("5", "Prefer Season Packs", str(cfg.get("prefer_season_packs", True)))
        table.add_row("6", "Quality Resolutions", ", ".join(cfg.get("resolutions") or []))
        table.add_row("7", "Seeding Policy", str(cfg.get("seeding_policy", "ratio")))
        table.add_row(
            "8", "Subtitle Languages", ", ".join(cfg.get("subtitle_languages") or ["en"])
        )
        table.add_row("9", "Subtitles Enabled", str(cfg.get("subtitles_enabled", True)))
        table.add_row(
            "10", "Max Download Speed (KB/s)", str(cfg.get("max_download_speed_kbps", 0))
        )
        table.add_row(
            "11", "Max Upload Speed (KB/s)", str(cfg.get("max_upload_speed_kbps", 0))
        )

        target.print(table)

        target.print("\n[bold]Options:[/bold]")
        target.print("  [1] View Full Configuration (JSON / Redacted)")
        target.print("  [2] Edit a Setting (1-11)")
        target.print("  [b] Back to Main Menu")

        choice = prompt_text(
            "Choose action [1, 2, b]", default="b", allow_back=True, c=target
        )
        if not choice or choice.lower() in ("b", "back"):
            return

        choice_clean = choice.strip().lower()

        if choice_clean in ("1", "v", "view"):
            redacted_data = json.dumps(cfg.redacted(), indent=2)
            target.print(
                Panel(redacted_data, title="Active Configuration (Redacted)", border_style="cyan")
            )
            prompt_text("Press Enter to continue", allow_back=False, c=target)
            continue

        if choice_clean in ("2", "e", "edit"):
            s_num = prompt_text("Enter setting number to edit [1-11]", c=target)
            if s_num:
                _handle_edit_setting(s_num.strip(), cfg, target)
            continue

        if choice_clean.startswith("e "):
            _handle_edit_setting(choice_clean[2:].strip(), cfg, target)
            continue

        if choice_clean.isdigit() and 3 <= int(choice_clean) <= 11:
            _handle_edit_setting(choice_clean, cfg, target)
            continue

        target.print(f"[red]Unknown choice '{choice}'.[/red]")


def _handle_edit_setting(choice: str, cfg: Config, target: Console) -> None:
    if choice == "1":
        val = prompt_text(
            "Enter new Download Root directory",
            default=str(cfg.get("download_root")),
            c=target,
        )
        if val:
            cfg.values["download_root"] = val.strip()
            save_config(cfg)
            target.print(f"[bold green]Updated download_root to '{val}'[/bold green]")

    elif choice == "2":
        val = prompt_text(
            "Enter new Library Root directory",
            default=str(cfg.get("library_root")),
            c=target,
        )
        if val:
            cfg.values["library_root"] = val.strip()
            save_config(cfg)
            target.print(f"[bold green]Updated library_root to '{val}'[/bold green]")

    elif choice == "3":
        target.print("Select Import Mode: [1] hardlink  [2] copy  [3] move")
        m_choice = prompt_text("Select [1-3]", default="1", c=target)
        mapping = {
            "1": "hardlink",
            "2": "copy",
            "3": "move",
            "hardlink": "hardlink",
            "copy": "copy",
            "move": "move",
        }
        new_mode = mapping.get((m_choice or "").strip().lower())
        if new_mode:
            cfg.values["import_mode"] = new_mode
            save_config(cfg)
            target.print(f"[bold green]Updated import_mode to '{new_mode}'[/bold green]")
        else:
            target.print("[red]Invalid import mode selection.[/red]")

    elif choice == "4":
        val = prompt_text(
            "Enter Max Concurrent Downloads (1-20)",
            default=str(cfg.get("max_concurrent_downloads")),
            c=target,
        )
        if val and val.isdigit() and int(val) > 0:
            cfg.values["max_concurrent_downloads"] = int(val)
            save_config(cfg)
            target.print(f"[bold green]Updated max_concurrent_downloads to {val}[/bold green]")
        else:
            target.print("[red]Invalid number.[/red]")

    elif choice == "5":
        curr = bool(cfg.get("prefer_season_packs", True))
        new_val = prompt_confirm(
            f"Prefer Season Packs? (currently {curr})", default=not curr, c=target
        )
        cfg.values["prefer_season_packs"] = new_val
        save_config(cfg)
        target.print(f"[bold green]Updated prefer_season_packs to {new_val}[/bold green]")

    elif choice == "6":
        curr_res = ", ".join(cfg.get("resolutions") or [])
        val = prompt_text(
            "Enter Quality Resolutions (e.g. 2160p, 1080p, 720p)",
            default=curr_res,
            c=target,
        )
        if val:
            res_list = [r.strip() for r in val.split(",") if r.strip()]
            if res_list:
                cfg.values["resolutions"] = res_list
                save_config(cfg)
                target.print(f"[bold green]Updated resolutions to {res_list}[/bold green]")

    elif choice == "7":
        target.print("Select Seeding Policy: [1] ratio  [2] time  [3] manual  [4] remove_on_import")
        p_choice = prompt_text("Select [1-4]", default="1", c=target)
        mapping = {"1": "ratio", "2": "time", "3": "manual", "4": "remove_on_import"}
        new_policy = mapping.get(
            (p_choice or "").strip().lower(), (p_choice or "").strip().lower()
        )
        if new_policy in ("ratio", "time", "manual", "remove_on_import"):
            cfg.values["seeding_policy"] = new_policy
            save_config(cfg)
            target.print(f"[bold green]Updated seeding_policy to '{new_policy}'[/bold green]")
        else:
            target.print("[red]Invalid seeding policy.[/red]")

    elif choice == "8":
        curr_langs = ", ".join(cfg.get("subtitle_languages") or ["en"])
        val = prompt_text(
            "Enter Subtitle Languages (comma-separated, e.g. en, es, fr)",
            default=curr_langs,
            c=target,
        )
        if val:
            langs = [lang.strip().lower() for lang in val.split(",") if lang.strip()]
            if langs:
                cfg.values["subtitle_languages"] = langs
                save_config(cfg)
                target.print(f"[bold green]Updated subtitle_languages to {langs}[/bold green]")

    elif choice == "9":
        curr = bool(cfg.get("subtitles_enabled", True))
        new_val = prompt_confirm(
            f"Enable Subtitles? (currently {curr})", default=not curr, c=target
        )
        cfg.values["subtitles_enabled"] = new_val
        save_config(cfg)
        target.print(f"[bold green]Updated subtitles_enabled to {new_val}[/bold green]")

    elif choice == "10":
        val = prompt_text(
            "Enter Max Download Speed KB/s (0 = unlimited)",
            default=str(cfg.get("max_download_speed_kbps", 0)),
            c=target,
        )
        if val and val.isdigit():
            cfg.values["max_download_speed_kbps"] = int(val)
            save_config(cfg)
            target.print(f"[bold green]Updated max_download_speed_kbps to {val}[/bold green]")

    elif choice == "11":
        val = prompt_text(
            "Enter Max Upload Speed KB/s (0 = unlimited)",
            default=str(cfg.get("max_upload_speed_kbps", 0)),
            c=target,
        )
        if val and val.isdigit():
            cfg.values["max_upload_speed_kbps"] = int(val)
            save_config(cfg)
            target.print(f"[bold green]Updated max_upload_speed_kbps to {val}[/bold green]")

    else:
        target.print(f"[red]Unknown option '{choice}'.[/red]")

    prompt_text("Press Enter to continue", allow_back=False, c=target)
