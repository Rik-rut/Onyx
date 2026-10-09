from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.panel import Panel

from arr.core.models import MediaType
from arr.core.parsing import explain
from arr.interactive.ui import (
    console,
    print_header,
    prompt_confirm,
    prompt_text,
    render_releases_table,
)
from arr.metadata.tvmaze import TvmazeClient, TvmazeError
from arr.pipeline import enqueue_release, search_candidates

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_tv(cfg: Config, c: Console | None = None) -> None:
    """Interactive TV show search, scope selection, release ranking, and download flow."""
    target = c or console
    print_header(
        "Search & Download TV Shows",
        "TVMaze metadata resolution & torrent search",
        target,
    )

    query = prompt_text("Enter TV show title", allow_back=True, c=target)
    if not query:
        return

    # 1. Metadata resolution via TVMaze
    target.print(f"[cyan]Searching TVMaze for '{query}'...[/cyan]")
    tvm = TvmazeClient(cfg)
    series_info = None
    try:
        raw = tvm.search_tv(query)
        if raw:
            series_info = tvm.full_series(raw["id"])
    except TvmazeError as e:
        target.print(f"[yellow]TVMaze lookup failed ({e}); falling back to direct search.[/yellow]")

    show_title = query
    tmdb_id = None
    imdb_id = None

    if series_info:
        show_title = series_info.title
        tmdb_id = series_info.tmdb_id
        imdb_id = series_info.imdb_id
        total_episodes = len(series_info.all_episodes())
        overview = (
            f"[bold white]{series_info.title}[/bold white] ({series_info.year or 'N/A'})\n"
            f"[cyan]Status:[/cyan] {series_info.status or 'Unknown'}   "
            f"[cyan]IMDb ID:[/cyan] {series_info.imdb_id or 'N/A'}\n"
            f"[cyan]Seasons:[/cyan] {len(series_info.seasons)}   "
            f"[cyan]Total Episodes:[/cyan] {total_episodes}"
        )
        target.print(Panel(overview, title="TVMaze Show Details", border_style="green"))
    else:
        target.print(
            f"[yellow]No TVMaze show found for '{query}'. Proceeding with direct search.[/yellow]"
        )

    # 2. Scope Selection
    target.print("\n[bold]Select Download Scope:[/bold]")
    target.print("  [1] Entire series (all seasons, season-pack priority)")
    target.print("  [2] Specific season")
    target.print("  [3] Specific episode")
    target.print("  [4] Direct indexer query (raw search)")
    target.print("  [b] Back to Main Menu")

    scope_choice = prompt_text("Choose scope", default="1", allow_back=True, c=target)
    if not scope_choice:
        return

    season_num: int | None = None
    episode_num: int | None = None
    search_query = show_title

    if scope_choice == "1":
        # Entire series scope
        target.print(f"\n[bold]Scope:[/bold] Entire Series for [cyan]{show_title}[/cyan]")
        if prompt_confirm(
            f"Enqueue entire series download for '{show_title}'?", default=True, c=target
        ):
            from arr.pipeline import download_tv

            target.print("[cyan]Resolving missing episodes and enqueuing torrents...[/cyan]")
            try:
                asyncio.run(
                    download_tv(
                        show_title,
                        cfg,
                        season=None,
                        episode=None,
                        pack=True,
                        auto=True,
                        yes=True,
                        no_wait=True,
                    )
                )
                target.print(
                    "[bold green]Entire series enqueued! Check queue for progress.[/bold green]"
                )
            except SystemExit as e:
                if e.code == 3:
                    target.print(
                        "[yellow]Nothing new to download (all episodes imported).[/yellow]"
                    )
                elif e.code == 4:
                    target.print(
                        "[bold red]Dependency unavailable (Transmission daemon offline).[/bold red]"
                    )
                else:
                    target.print(f"[bold red]Download failed with code {e.code}.[/bold red]")
            except Exception as e:
                target.print(f"[bold red]Error during series download: {e}[/bold red]")
            prompt_text("Press Enter to continue", allow_back=False, c=target)
            return
        else:
            target.print("[dim]Entire series enqueue cancelled.[/dim]")
            return

    elif scope_choice == "2":
        s_input = prompt_text("Enter season number (e.g. 1)", allow_back=True, c=target)
        if not s_input or not s_input.isdigit():
            target.print("[yellow]Invalid season number.[/yellow]")
            return
        season_num = int(s_input)
        target.print(f"[cyan]Searching Season {season_num} for '{show_title}'...[/cyan]")

    elif scope_choice == "3":
        s_input = prompt_text("Enter season number (e.g. 1)", allow_back=True, c=target)
        if not s_input or not s_input.isdigit():
            target.print("[yellow]Invalid season number.[/yellow]")
            return
        season_num = int(s_input)
        e_input = prompt_text("Enter episode number (e.g. 1)", allow_back=True, c=target)
        if not e_input or not e_input.isdigit():
            target.print("[yellow]Invalid episode number.[/yellow]")
            return
        episode_num = int(e_input)
        target.print(
            f"[cyan]Searching S{season_num:02d}E{episode_num:02d} for '{show_title}'...[/cyan]"
        )

    elif scope_choice == "4":
        raw_q = prompt_text("Enter search query", default=show_title, allow_back=True, c=target)
        if not raw_q:
            return
        search_query = raw_q
        target.print(f"[cyan]Searching indexers for '{search_query}'...[/cyan]")

    else:
        target.print(f"[red]Unknown scope option '{scope_choice}'.[/red]")
        return

    # 3. Search indexers and rank releases
    try:
        releases, scored, q_obj = asyncio.run(
            search_candidates(
                MediaType.TV,
                search_query,
                cfg,
                season=season_num,
                episode=episode_num,
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

    # 4. Display ranked releases & interactive selection loop
    target.print(render_releases_table(releases, target))

    while True:
        action = prompt_text(
            f"Select release [0-{len(releases)-1}], 'auto', 'explain <#>', or 'b' to go back",
            allow_back=True,
            c=target,
        )
        if not action or action.lower() in ("b", "back"):
            return

        action_clean = action.strip().lower()
        if action_clean == "auto":
            chosen = releases[0]
            break

        if action_clean.startswith("explain"):
            parts = action_clean.split()
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

        if action_clean.isdigit():
            idx = int(action_clean)
            if 0 <= idx < len(releases):
                chosen = releases[idx]
                break
            else:
                target.print(f"[red]Release index {idx} out of range [0-{len(releases)-1}].[/red]")
        else:
            target.print("[red]Invalid selection. Enter a number, 'auto', 'explain', or 'b'.[/red]")

    # 5. Enqueue chosen release
    target.print(f"\n[bold]Selected:[/bold] {chosen.title}")
    if prompt_confirm("Start download?", default=True, c=target):
        ok, msg = asyncio.run(
            enqueue_release(
                chosen,
                cfg,
                media_type="tv",
                season=season_num,
                episode=episode_num,
                tmdb_id=tmdb_id,
                imdb_id=imdb_id,
            )
        )
        if ok:
            target.print(f"[bold green]{msg}! Infohash: {chosen.infohash[:10]}[/bold green]")
        else:
            target.print(f"[bold red]{msg}[/bold red]")
    else:
        target.print("[dim]Download cancelled.[/dim]")

    prompt_text("Press Enter to continue", allow_back=False, c=target)
