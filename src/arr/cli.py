from __future__ import annotations

import asyncio
import json
from typing import Any

import typer

from arr import __version__
from arr.config import default_config_path, init_config, load_config
from arr.core.models import MediaType
from arr.exit import ExitCode
from arr.log import configure_logging, get_logger

app = typer.Typer(no_args_is_help=True, add_completion=False)
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
    configure_logging(cfg)
    return cfg


@app.callback()
def main(
    ctx: typer.Context,
    config: str | None = typer.Option(None, "--config", help="Path to config.toml"),
) -> None:
    ctx.obj = {"config_path": config}


@search_app.command("movie")
def search_movie(
    ctx: typer.Context,
    query: str,
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from arr.pipeline import search

    cfg = _config(ctx)
    try:
        results = asyncio.run(search(MediaType.MOVIE, query, cfg))
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
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    from arr.pipeline import search

    cfg = _config(ctx)
    try:
        results = asyncio.run(search(MediaType.TV, query, cfg, season=season, episode=episode))
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
def status(ctx: typer.Context, download_id: str, json_out: bool = typer.Option(False, "--json")) -> None:
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


@app.command("import")
def import_cmd(ctx: typer.Context, download_id: str, overwrite: bool = typer.Option(False, "--overwrite")) -> None:
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
        asyncio.run(run_daemon(cfg))
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
