from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from rich.panel import Panel

from arr.core.models import MediaType, Release
from arr.core.parsing import explain
from arr.interactive.ui import (
    console,
    live_monitor_downloads,
    parse_episode_selection,
    print_header,
    prompt_confirm,
    prompt_text,
    render_episodes_table,
    render_matches_table,
    render_releases_table,
    render_seasons_table,
)
from arr.metadata.tvmaze import TvmazeClient, TvmazeError
from arr.pipeline import _staging_dir, check_disk_space, enqueue_release, search_candidates

if TYPE_CHECKING:
    from rich.console import Console

    from arr.config.settings import Config


def interactive_tv(cfg: Config, c: Console | None = None) -> None:
    """Interactive TV show search, close matches selection, and live progress monitor."""
    target = c or console
    print_header(
        "Search & Download TV Shows",
        "TVMaze metadata resolution & torrent search",
        target,
    )

    query = prompt_text("Enter TV show title", allow_back=True, c=target)
    if not query:
        return

    # 1. Metadata resolution via TVMaze with Rich spinner
    tvm = TvmazeClient(cfg)
    matches: list[dict] = []
    with target.status(f"[bold cyan]Searching TVMaze for '{query}'...[/bold cyan]", spinner="dots"):
        try:
            matches = tvm.search_tv_shows(query)
        except Exception:
            pass
        if not matches:
            try:
                s = tvm.search_tv(query)
                if s:
                    matches = [s]
            except Exception:
                pass

    chosen_match: dict | None = None
    if len(matches) > 1:
        target.print(render_matches_table(matches, "TV Show", target))
        while True:
            m_choice = prompt_text(
                f"Select TV show [0-{len(matches)-1}] or 'b' to go back",
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

    series_info = None
    seasons: list[dict] = []
    if chosen_match and chosen_match.get("id"):
        try:
            series_info = tvm.full_series(int(chosen_match["id"]))
            seasons = tvm.seasons_overview(int(chosen_match["id"]), series=series_info)
        except TvmazeError as e:
            target.print(
                f"[yellow]TVMaze lookup failed ({e}); falling back to direct search.[/yellow]"
            )

    show_title = query
    tmdb_id = None
    imdb_id = None

    if chosen_match:
        show_title = chosen_match.get("title") or chosen_match.get("name") or query
        tmdb_id = chosen_match.get("id")
        ext = chosen_match.get("externals") or {}
        imdb_id = ext.get("imdb")

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
    elif chosen_match:
        target.print(
            Panel(
                f"[bold white]{show_title}[/bold white]",
                title="TVMaze Show Match",
                border_style="green",
            )
        )
    else:
        target.print(
            f"[yellow]No TVMaze show found for '{query}'. Proceeding with direct search.[/yellow]"
        )

    # Display seasons overview table with status (Completed, Ongoing, Upcoming)
    if seasons:
        target.print(render_seasons_table(seasons, target))

    # 2. Scope Selection
    target.print("\n[bold]Select Download Scope:[/bold]")
    target.print("  [1] Entire series (all seasons, season-pack priority)")
    target.print("  [2] Specific season (browse seasons & select episodes)")
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
                if prompt_confirm("Monitor download progress live?", default=False, c=target):
                    live_monitor_downloads(cfg, target, auto_exit_when_done=True)
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

        matched_season = (
            next((s for s in series_info.seasons if s.season_number == season_num), None)
            if series_info
            else None
        )

        if matched_season and matched_season.episodes:
            target.print(render_episodes_table(matched_season.episodes, target))
            target.print("\n[bold]Season Download Options:[/bold]")
            target.print("  [1] Download entire season (season pack)")
            target.print("  [2] Select specific episode(s)")
            target.print("  [b] Back to Main Menu")

            s_opt = prompt_text("Choose option", default="1", allow_back=True, c=target)
            if not s_opt:
                return

            if s_opt in ("2", "episodes"):
                ep_text = prompt_text(
                    f"Select episode(s) (e.g. '1', '1, 3, 5', '1-4', 'all' "
                    f"[max {len(matched_season.episodes)}])",
                    allow_back=True,
                    c=target,
                )
                if not ep_text:
                    return
                try:
                    selected_eps = parse_episode_selection(
                        ep_text, max_ep=len(matched_season.episodes)
                    )
                except ValueError as err:
                    target.print(f"[red]Invalid selection: {err}[/red]")
                    return

                if len(selected_eps) == 1:
                    episode_num = selected_eps[0]
                    target.print(
                        f"[cyan]Searching S{season_num:02d}E{episode_num:02d} "
                        f"for '{show_title}'...[/cyan]"
                    )
                else:
                    # Multi-episode download
                    target.print(
                        f"\n[bold]Selected {len(selected_eps)} episodes:[/bold] "
                        + ", ".join(f"E{e:02d}" for e in selected_eps)
                    )
                    if not prompt_confirm(
                        "Start download for selected episodes?", default=True, c=target
                    ):
                        target.print("[dim]Episode download cancelled.[/dim]")
                        return

                    target.print(
                        f"[cyan]Searching and enqueuing {len(selected_eps)} episodes...[/cyan]"
                    )
                    enqueued_count = 0
                    for ep_n in selected_eps:
                        try:
                            rel_list, _, _ = asyncio.run(
                                search_candidates(
                                    MediaType.TV,
                                    show_title,
                                    cfg,
                                    season=season_num,
                                    episode=ep_n,
                                    year=series_info.year if series_info else None,
                                    tmdb_id=tmdb_id,
                                    imdb_id=imdb_id,
                                    title=show_title,
                                )
                            )
                            if rel_list:
                                best = rel_list[0]
                                ok, msg = asyncio.run(
                                    enqueue_release(
                                        best,
                                        cfg,
                                        media_type="tv",
                                        season=season_num,
                                        episode=ep_n,
                                        tmdb_id=tmdb_id,
                                        imdb_id=imdb_id,
                                    )
                                )
                                if ok:
                                    target.print(f"[green]✓ E{ep_n:02d}: {best.title[:60]}[/green]")
                                    enqueued_count += 1
                                else:
                                    target.print(f"[yellow]! E{ep_n:02d}: {msg}[/yellow]")
                            else:
                                target.print(f"[yellow]✗ E{ep_n:02d}: No releases found[/yellow]")
                        except Exception as ex:
                            target.print(f"[red]✗ E{ep_n:02d}: Error ({ex})[/red]")

                    target.print(
                        f"[bold green]Enqueued {enqueued_count}/"
                        f"{len(selected_eps)} episodes.[/bold green]"
                    )
                    if enqueued_count > 0 and prompt_confirm(
                        "Monitor download progress live?", default=False, c=target
                    ):
                        live_monitor_downloads(cfg, target, auto_exit_when_done=True)
                    prompt_text("Press Enter to continue", allow_back=False, c=target)
                    return
            else:
                target.print(f"[cyan]Searching Season {season_num} for '{show_title}'...[/cyan]")
        else:
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

    # 3. Search indexers and rank releases with Rich spinner
    with target.status(
        f"[bold cyan]Searching indexers and ranking releases for '{search_query}'...[/bold cyan]",
        spinner="dots",
    ):
        try:
            releases, scored, q_obj = asyncio.run(
                search_candidates(
                    MediaType.TV,
                    search_query,
                    cfg,
                    season=season_num,
                    episode=episode_num,
                    year=series_info.year if series_info else None,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    title=show_title,
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

    # 4. Display ranked releases & interactive selection loop with filtering/sorting
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

    # 5. Pre-flight disk space verification (R19.4)
    staging = _staging_dir(cfg, "tv")
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

    # 6. Enqueue chosen release
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
            if prompt_confirm("Monitor download progress live?", default=False, c=target):
                live_monitor_downloads(
                    cfg, target, single_hash=chosen.infohash, auto_exit_when_done=True
                )
        else:
            target.print(f"[bold red]{msg}[/bold red]")
    else:
        target.print("[dim]Download cancelled.[/dim]")

    prompt_text("Press Enter to continue", allow_back=False, c=target)
