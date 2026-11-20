from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import typer

from arr import __version__
from arr.config import default_config_path, init_config, load_config
from arr.core.models import MediaType
from arr.exit import ExitCode
from arr.log import configure_logging, get_logger

app = typer.Typer(no_args_is_help=False, add_completion=False)
search_app = typer.Typer(no_args_is_help=True)
download_app = typer.Typer(no_args_is_help=True)
series_app = typer.Typer(no_args_is_help=True)
config_app = typer.Typer(no_args_is_help=True)

app.add_typer(search_app, name="search")
app.add_typer(download_app, name="download")
app.add_typer(series_app, name="series")
app.add_typer(config_app, name="config")

log = get_logger("cli")


def _emit(data: Any, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        if isinstance(data, str):
            typer.echo(data)
        else:
            typer.echo(json.dumps(data, indent=2, default=str))


def _config(ctx: typer.Context):
    path = ctx.obj.get("config_path") if ctx.obj else None
    cfg = load_config(path)
    override = ctx.obj.get("transmission_remote") if ctx.obj else None
    if override:
        cfg.values["transmission_remote"] = override
    configure_logging(cfg)
    return cfg


@app.command("interactive")
def interactive_cmd(ctx: typer.Context) -> None:
    """Launch the interactive terminal application."""
    from arr.interactive import run_interactive

    cfg = _config(ctx)
    try:
        run_interactive(cfg)
    except KeyboardInterrupt:
        typer.echo("\nGoodbye!")


@app.command("web")
def web_cmd(
    ctx: typer.Context,
    host: str = typer.Option("0.0.0.0", "--host", help="Host interface to bind on"),
    port: int = typer.Option(3698, "--port", help="Port to listen on"),
    open_browser: bool = typer.Option(
        True, "--open-browser/--no-open-browser", help="Open browser on start"
    ),
) -> None:
    """Launch the Web UI dashboard."""
    import sys
    import threading
    import time
    import webbrowser

    import uvicorn

    from arr.interactive import run_interactive
    from arr.transmission.process import ensure_daemon, port_in_use
    from arr.web.app import create_app

    cfg = _config(ctx)
    t_port = int(cfg.get("transmission_rpc_port", 9091))
    was_running = port_in_use(t_port, timeout=0.1)
    daemon_proc = None
    if not was_running:
        try:
            daemon_proc = ensure_daemon(cfg)
            log.info("Auto-started Transmission daemon on port %d", t_port)
        except Exception as e:
            log.warning("Could not auto-start transmission-daemon: %s", e)

    web_app = create_app(cfg)
    disp_host = "localhost" if host in ("0.0.0.0", "127.0.0.1") else host
    url = f"http://{disp_host}:{port}"

    config = uvicorn.Config(
        web_app,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        log_config=None,
    )
    server = uvicorn.Server(config)

    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    time.sleep(0.5)

    if open_browser:
        try:
            webbrowser.open_new_tab(url)
        except Exception:
            pass

    typer.echo("")
    typer.echo("=" * 60)
    typer.echo("               ONYX Web UI Dashboard Running")
    typer.echo(f"  URL: {url}")
    typer.echo("=" * 60)
    typer.echo("  [C] Launch Interactive CLI Dashboard")
    typer.echo("  [Q] Exit Web Server (or Ctrl+C)")
    typer.echo("=" * 60)
    typer.echo("")

    if not sys.stdin or not sys.stdin.isatty():
        try:
            while server_thread.is_alive():
                time.sleep(1)
        except KeyboardInterrupt:
            server.should_exit = True
        server_thread.join(timeout=3)
        if daemon_proc is not None:
            try:
                daemon_proc.stop()
            except Exception:
                pass
        return

    def _read_key() -> str | None:
        if sys.platform == "win32":
            try:
                import msvcrt

                if msvcrt.kbhit():
                    ch = msvcrt.getch()
                    if ch in (b"\x00", b"\xe0"):
                        if msvcrt.kbhit():
                            msvcrt.getch()
                        return None
                    try:
                        return ch.decode("utf-8", errors="ignore").lower()
                    except Exception:
                        return None
            except Exception:
                pass
        else:
            try:
                import select

                if sys.stdin and sys.stdin.isatty():
                    r, _, _ = select.select([sys.stdin], [], [], 0)
                    if r:
                        return sys.stdin.read(1).lower()
            except Exception:
                pass
        return None

    try:
        while server_thread.is_alive():
            key = _read_key()
            if key == "c":
                typer.echo("\n[CLI] Launching Interactive CLI Dashboard...\n")
                try:
                    run_interactive(cfg)
                except KeyboardInterrupt:
                    pass
                typer.echo("")
                typer.echo("=" * 60)
                typer.echo("               ONYX Web UI Dashboard Running")
                typer.echo(f"  URL: {url}")
                typer.echo("=" * 60)
                typer.echo("  [C] Launch Interactive CLI Dashboard")
                typer.echo("  [Q] Exit Web Server (or Ctrl+C)")
                typer.echo("=" * 60)
                typer.echo("")
            elif key in ("q", "\x03"):
                typer.echo("\nShutting down web server...")
                server.should_exit = True
                break
            time.sleep(0.1)
    except (KeyboardInterrupt, EOFError):
        typer.echo("\nShutting down web server...")
        server.should_exit = True

    server_thread.join(timeout=3)
    if daemon_proc is not None:
        try:
            daemon_proc.stop()
            typer.echo("Stopped background Transmission daemon.")
        except Exception:
            pass


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    config: str | None = typer.Option(None, "--config", help="Path to config.toml"),
    transmission_remote: str | None = typer.Option(
        None, "--transmission-remote", help="Path to the transmission-remote binary"
    ),
) -> None:
    ctx.obj = {
        "config_path": Path(config) if config else None,
        "transmission_remote": transmission_remote,
    }
    if ctx.invoked_subcommand is None:
        web_cmd(ctx, open_browser=True)


@search_app.command("movie")
def search_movie(
    ctx: typer.Context,
    query: str,
    explain: bool = typer.Option(False, "--explain", help="Print filter/score details to stderr"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from arr.pipeline import search

    cfg = _config(ctx)
    try:
        results = asyncio.run(search(MediaType.MOVIE, query, cfg, explain_mode=explain))
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)
    if not results:
        typer.echo("No results.", err=True)
        raise typer.Exit(ExitCode.NO_RESULTS)
    _emit([r.model_dump() for r in results], json_out)


@search_app.command("tv")
def search_tv(
    ctx: typer.Context,
    query: str,
    season: int | None = typer.Option(None, "-s"),
    episode: int | None = typer.Option(None, "-e"),
    explain: bool = typer.Option(False, "--explain", help="Print filter/score details to stderr"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from arr.pipeline import search

    cfg = _config(ctx)
    try:
        results = asyncio.run(
            search(MediaType.TV, query, cfg, season=season, episode=episode, explain_mode=explain)
        )
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)
    if not results:
        typer.echo("No results.", err=True)
        raise typer.Exit(ExitCode.NO_RESULTS)
    _emit([r.model_dump() for r in results], json_out)


@download_app.command("movie")
def download_movie(
    ctx: typer.Context,
    query: str,
    pick: int | None = typer.Option(None, "--pick"),
    auto: bool = typer.Option(False, "--auto"),
    yes: bool = typer.Option(False, "--yes"),
    no_wait: bool = typer.Option(False, "--no-wait"),
    force: bool = typer.Option(False, "--force"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from arr.pipeline import download_movie as _dm

    cfg = _config(ctx)
    try:
        asyncio.run(_dm(query, cfg, pick=pick, auto=auto, yes=yes, no_wait=no_wait, force=force))
    except typer.Exit:
        raise
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@download_app.command("tv")
def download_tv(
    ctx: typer.Context,
    query: str,
    season: int | None = typer.Option(None, "-s"),
    episode: int | None = typer.Option(None, "-e"),
    pack: bool = typer.Option(False, "--pack"),
    pick: int | None = typer.Option(None, "--pick"),
    auto: bool = typer.Option(False, "--auto"),
    yes: bool = typer.Option(False, "--yes"),
    no_wait: bool = typer.Option(False, "--no-wait"),
    force: bool = typer.Option(False, "--force"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from arr.pipeline import download_tv as _dt

    cfg = _config(ctx)
    try:
        asyncio.run(
            _dt(
                query,
                cfg,
                season=season,
                episode=episode,
                pack=pack,
                pick=pick,
                auto=auto,
                yes=yes,
                no_wait=no_wait,
                force=force,
            )
        )
    except typer.Exit:
        raise
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@download_app.command("magnet")
def download_magnet_cmd(
    ctx: typer.Context,
    uri: str,
    auto: bool = typer.Option(False, "--auto"),
    no_wait: bool = typer.Option(False, "--no-wait"),
) -> None:
    from arr.pipeline import download_magnet as _dm_magnet

    cfg = _config(ctx)
    try:
        asyncio.run(_dm_magnet(uri, cfg, auto=auto, no_wait=no_wait))
    except typer.Exit:
        raise
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@series_app.command("add")
def series_add(ctx: typer.Context, query: str) -> None:
    from arr.pipeline import series_add as _sa

    cfg = _config(ctx)
    try:
        asyncio.run(_sa(query, cfg))
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@series_app.command("list")
def series_list(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
    from arr.pipeline import series_list as _sl

    cfg = _config(ctx)
    _emit(_sl(cfg), json_out)


@series_app.command("remove")
def series_remove(
    ctx: typer.Context, series_id: int, delete_files: bool = typer.Option(False, "--delete-files")
) -> None:
    from arr.pipeline import series_remove as _sr

    cfg = _config(ctx)
    _sr(series_id, cfg, delete_files=delete_files)


@series_app.command("check")
def series_check(ctx: typer.Context, series_id: int) -> None:
    from arr.pipeline import series_check as _sc

    cfg = _config(ctx)
    try:
        asyncio.run(_sc(series_id, cfg))
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@app.command("queue")
def queue(ctx: typer.Context, json_out: bool = typer.Option(False, "--json")) -> None:
    from arr.pipeline import list_queue

    cfg = _config(ctx)
    _emit(list_queue(cfg), json_out)


@app.command("status")
def status(
    ctx: typer.Context, download_id: str, json_out: bool = typer.Option(False, "--json")
) -> None:
    from arr.pipeline import get_status

    cfg = _config(ctx)
    _emit(get_status(download_id, cfg), json_out)


@app.command("cancel")
def cancel(
    ctx: typer.Context,
    download_id: str,
    delete_data: bool = typer.Option(False, "--delete-data"),
) -> None:
    from arr.pipeline import cancel_download

    cfg = _config(ctx)
    try:
        asyncio.run(cancel_download(download_id, cfg, delete_data=delete_data))
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@app.command("pause")
def pause_cmd(ctx: typer.Context, download_id: str) -> None:
    from arr.pipeline import pause_download

    cfg = _config(ctx)
    try:
        asyncio.run(pause_download(download_id, cfg))
        typer.echo(f"Paused download {download_id}.")
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@app.command("resume")
def resume_cmd(ctx: typer.Context, download_id: str) -> None:
    from arr.pipeline import resume_download

    cfg = _config(ctx)
    try:
        asyncio.run(resume_download(download_id, cfg))
        typer.echo(f"Resumed download {download_id}.")
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@app.command("import")
def import_cmd(
    ctx: typer.Context,
    download_id: str,
    overwrite: bool = typer.Option(False, "--overwrite"),
) -> None:
    from arr.pipeline import import_download

    cfg = _config(ctx)
    try:
        asyncio.run(import_download(download_id, cfg, overwrite=overwrite))
    except Exception as e:
        log.error("%s", e)
        raise typer.Exit(ExitCode.RUNTIME_ERROR)


@app.command("daemon")
def daemon(ctx: typer.Context) -> None:
    from arr.pipeline import run_daemon

    cfg = _config(ctx)
    try:
        run_daemon(cfg)
    except KeyboardInterrupt:
        pass


@config_app.command("init")
def config_init(ctx: typer.Context) -> None:
    path = ctx.obj.get("config_path") if ctx.obj else None
    p = init_config(path)
    typer.echo(f"Config written to {p}")


@config_app.command("show")
def config_show(
    ctx: typer.Context,
    show_secrets: bool = typer.Option(False, "--show-secrets"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    cfg = _config(ctx)
    data = dict(cfg.values) if show_secrets else cfg.redacted()
    _emit(data, json_out)


@config_app.command("path")
def config_path(ctx: typer.Context) -> None:
    path = ctx.obj.get("config_path") if ctx.obj else None
    typer.echo(str(path or default_config_path()))


@app.command("version")
def version() -> None:
    typer.echo(__version__)
