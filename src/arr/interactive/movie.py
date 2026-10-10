from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.panel import Panel

from arr.core.models import MediaType, Release
from arr.core.parsing import explain
from arr.interactive.ui import (
    console,
    live_monitor_downloads,
    print_header,
    prompt_confirm,
    prompt_text,
    render_matches_table,
    render_releases_table,
)
from arr.metadata.imdb import ImdbClient
from arr.pipeline import _staging_dir, check_disk_space, enqueue_release, search_candidates

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_movie(cfg: Config, c: Console | None = None) -> None:
    """Interactive movie search, IMDb metadata resolution, release ranking, and download flow."""
    target = c or console
    print_header("Search & Download Movies", "IMDb metadata resolution & torrent search", target)

    query = prompt_text("Enter movie title", allow_back=True, c=target)
    if not query:
        return

    # 1. Metadata resolution via IMDb with Rich spinner
    imdb = ImdbClient(cfg)
    matches: list[dict] = []
    with target.status(f"[bold cyan]Searching IMDb for '{query}'...[/bold cyan]", spinner="dots"):
        try:
            matches = imdb.search_movies(query)
        except Exception:
            pass
        if not matches:
            try:
                m = imdb.search_movie(query)
                if m:
                    matches = [m]
            except Exception:
                pass

    chosen_match: dict | None = None
    if len(matches) > 1:
        target.print(render_matches_table(matches, "Movie", target))
        while True:
            m_choice = prompt_text(
                f"Select movie [0-{len(matches)-1}] or 'b' to go back",
                default="0",
                allow_back=True,
                c=target,
            )
            if not m_choice or m_choice.lower() in ("b", "back"):
                return
            if m_choice.isdigit() and 0 <= int(m_choice) < len(matches):
                chosen_match = matches[int(m_choice)]
                break
            target.print(f"[red]Invalid selection. Enter 0 to {len(matches)-1}.[/red]")
    elif len(matches) == 1:
        chosen_match = matches[0]

    search_query = query
    imdb_id = None
    year = None

    if chosen_match:
        search_query = chosen_match.get("title") or query
        imdb_id = chosen_match.get("imdb_id") or chosen_match.get("id")
        year = chosen_match.get("year")
        overview = (
            f"[bold white]{search_query}[/bold white] ({year or 'N/A'})\n"
            f"[cyan]IMDb ID:[/cyan] {imdb_id or 'N/A'}"
        )
        target.print(Panel(overview, title="IMDb Movie Details", border_style="green"))
    else:
        target.print(
            f"[yellow]No IMDb match found for '{query}'. Proceeding with direct search.[/yellow]"
        )

    # 2. Search indexers and rank releases with Rich spinner
    with target.status(
        f"[bold cyan]Searching indexers and ranking releases for '{search_query}'...[/bold cyan]",
        spinner="dots",
    ):
        try:
            releases, scored, q_obj = asyncio.run(
                search_candidates(
                    MediaType.MOVIE,
                    search_query,
                    cfg,
                    year=year,
                    imdb_id=imdb_id,
                    title=search_query,
                )
            )
        except Exception as e:
            target.print(f"[bold red]Search failed: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)
            return

    if not releases:
        target.print("[yellow]No releases found matching criteria.[/yellow]")
        prompt_text("Press Enter to continue", allow_back=False, c=target)
        return

    # 3. Display ranked releases & interactive selection loop with filtering/sorting
    current_releases: list[Release] = list(releases)
    target.print(render_releases_table(current_releases, target))

    chosen: Release | None = None
    while True:
        prompt_hint = (
            f"Select [0-{len(current_releases)-1}], 'f <text>', 'sort <seeds|size|score>', "
            "'auto', 'explain <#>', or 'b'"
        )
        action = prompt_text(prompt_hint, allow_back=True, c=target)
        if not action or action.lower() in ("b", "back"):
            return

        action_clean = action.strip()
        action_lower = action_clean.lower()

        if action_lower == "auto":
            chosen = current_releases[0]
            break

        # Instant filtering: f 1080p, f hevc, f reset
        if action_lower.startswith("f ") or action_lower == "f":
            pattern = action_lower[2:].strip()
            if not pattern or pattern == "reset":
                current_releases = list(releases)
                target.print("[bold cyan]Reset release filter.[/bold cyan]")
            else:
                filtered = [r for r in releases if pattern in r.title.lower()]
                if filtered:
                    current_releases = filtered
                    target.print(
                        f"[bold cyan]Filtered to {len(current_releases)} releases "
                        f"matching '{pattern}':[/bold cyan]"
                    )
                else:
                    target.print(f"[yellow]No releases match '{pattern}'.[/yellow]")
                    continue
            target.print(render_releases_table(current_releases, target))
            continue

        # Instant sorting: sort seeds, sort size, sort score
        if action_lower.startswith("sort "):
            sort_key = action_lower[5:].strip()
            if sort_key == "seeds":
                current_releases.sort(key=lambda r: r.seeds, reverse=True)
                target.print("[bold cyan]Sorted releases by seeders descending:[/bold cyan]")
            elif sort_key == "size":
                current_releases.sort(key=lambda r: r.size_bytes, reverse=True)
                target.print("[bold cyan]Sorted releases by size descending:[/bold cyan]")
            elif sort_key == "score":
                current_releases = list(releases)
                target.print("[bold cyan]Reset releases to default ranked score order:[/bold cyan]")
            else:
                target.print(
                    f"[yellow]Unknown sort key '{sort_key}' (use seeds, size, or score).[/yellow]"
                )
                continue
            target.print(render_releases_table(current_releases, target))
            continue

        if action_lower.startswith("explain"):
            parts = action_lower.split()
            if len(parts) > 1 and parts[1].isdigit():
                idx = int(parts[1])
                if 0 <= idx < len(scored):
                    target.print(
                        Panel(
                            explain([scored[idx]]),
                            title=f"Score Breakdown for #{idx}",
                            border_style="yellow",
                        )
                    )
                else:
                    target.print(f"[red]Index #{idx} out of range.[/red]")
            else:
                target.print(
                    Panel(
                        explain(scored),
                        title="Full Candidate Score Breakdown",
                        border_style="yellow",
                    )
                )
            continue

        if action_lower.isdigit():
            idx = int(action_lower)
            if 0 <= idx < len(current_releases):
                chosen = current_releases[idx]
                break
            else:
                target.print(
                    f"[red]Release index {idx} out of range [0-{len(current_releases)-1}].[/red]"
                )
        else:
            target.print("[red]Invalid command. Enter number, 'f <pattern>', 'sort', or 'b'.[/red]")

    if chosen is None:
        return

    # 4. Pre-flight disk space verification (R19.4)
    staging = _staging_dir(cfg, "movie")
    if getattr(chosen, "size_bytes", 0) > 0:
        has_space, free_b, req_b = check_disk_space(staging, chosen.size_bytes)
        if not has_space:
            gb_free = free_b / (1024**3)
            gb_req = req_b / (1024**3)
            target.print(
                f"[bold red]WARNING: Release size ({gb_req:.1f} GB) exceeds "
                f"available disk space ({gb_free:.1f} GB)![/bold red]"
            )
            if not prompt_confirm("Proceed with download anyway?", default=False, c=target):
                target.print("[yellow]Download aborted due to low disk space.[/yellow]")
                prompt_text("Press Enter to continue", allow_back=False, c=target)
                return

    # 5. Enqueue chosen release
    target.print(f"\n[bold]Selected:[/bold] {chosen.title}")
    if prompt_confirm("Start download?", default=True, c=target):
        ok, msg = asyncio.run(
            enqueue_release(
                chosen,
                cfg,
                media_type="movie",
                imdb_id=imdb_id,
            )
        )
        if ok:
            target.print(f"[bold green]{msg}! Infohash: {chosen.infohash[:10]}[/bold green]")
            if prompt_confirm("Monitor download progress live?", default=False, c=target):
                live_monitor_downloads(
                    cfg, target, single_hash=chosen.infohash, auto_exit_when_done=True
                )
        else:
            target.print(f"[bold red]{msg}[/bold red]")
    else:
        target.print("[dim]Download cancelled.[/dim]")

    prompt_text("Press Enter to continue", allow_back=False, c=target)
