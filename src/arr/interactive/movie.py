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
from arr.metadata.imdb import ImdbClient, ImdbError
from arr.pipeline import enqueue_release, search_candidates

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

    # 1. Metadata resolution via IMDb
    target.print(f"[cyan]Searching IMDb for '{query}'...[/cyan]")
    imdb = ImdbClient(cfg)
    movie_info = None
    try:
        movie_info = imdb.search_movie(query)
    except ImdbError as e:
        target.print(f"[yellow]IMDb lookup failed ({e}); falling back to direct search.[/yellow]")

    search_query = query
    imdb_id = None
    year = None

    if movie_info:
        search_query = movie_info.get("title") or query
        imdb_id = movie_info.get("imdb_id") or movie_info.get("id")
        year = movie_info.get("year")
        overview = (
            f"[bold white]{search_query}[/bold white] ({year or 'N/A'})\n"
            f"[cyan]IMDb ID:[/cyan] {imdb_id or 'N/A'}"
        )
        target.print(Panel(overview, title="IMDb Movie Details", border_style="green"))
    else:
        target.print(
            f"[yellow]No IMDb match found for '{query}'. Proceeding with direct search.[/yellow]"
        )

    # 2. Search indexers and rank releases
    target.print(f"[cyan]Searching indexers for '{search_query}'...[/cyan]")
    try:
        releases, scored, q_obj = asyncio.run(
            search_candidates(
                MediaType.MOVIE,
                search_query,
                cfg,
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

    # 3. Display ranked releases & interactive selection loop
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

    # 4. Enqueue chosen release
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
        else:
            target.print(f"[bold red]{msg}[/bold red]")
    else:
        target.print("[dim]Download cancelled.[/dim]")

    prompt_text("Press Enter to continue", allow_back=False, c=target)
