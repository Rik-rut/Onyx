from pathlib import Path

from arr.config.settings import DEFAULTS, Config, init_config, load_config


def test_init_config_creates_parent_and_template(tmp_path):
    p = tmp_path / "nested" / "arr" / "config.toml"
    result = init_config(p)
    assert result == p
    assert p.exists()
    assert "tvmaze_base_url" in p.read_text(encoding="utf-8")


def test_init_config_is_idempotent(tmp_path):
    p = tmp_path / "arr" / "config.toml"
    init_config(p)
    p.write_text('download_root = "custom"\n', encoding="utf-8")
    init_config(p)
    assert 'download_root = "custom"' in p.read_text(encoding="utf-8")


def test_load_config_accepts_string_path(tmp_path):
    p = tmp_path / "arr" / "config.toml"
    init_config(p)
    cfg = load_config(str(p))
    assert cfg.get("download_root") == "downloads"


def test_load_config_overrides_defaults(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('download_root = "D:/media"\nmin_seeders = 5\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.get("download_root") == "D:/media"
    assert cfg.get("min_seeders") == 5


def test_redacted_hides_password_only():
    cfg = Config(values=dict(DEFAULTS, transmission_rpc_pass="hunter2"))
    redacted = cfg.redacted()
    assert redacted["transmission_rpc_pass"] == "***redacted***"
    assert cfg.values["transmission_rpc_pass"] == "hunter2"


def test_default_config_path_is_platform_appropriate():
    from arr.config.settings import default_config_path

    p = Path(default_config_path())
    assert p.name == "config.toml"
    assert "arr" in p.parts


def test_config_template_documents_every_default_key():
    """`config init` must document every configurable key (R1)."""
    import re

    from arr.config.settings import CONFIG_TEMPLATE, DEFAULTS

    tmpl_keys = set(re.findall(r"^([a-z0-9_]+)\s*=", CONFIG_TEMPLATE, re.M))
    missing = set(DEFAULTS) - tmpl_keys
    assert not missing, f"undocumented default keys: {sorted(missing)}"


def test_config_template_round_trips(tmp_path):
    from arr.config.settings import init_config, load_config

    p = tmp_path / "config.toml"
    init_config(p)
    cfg = load_config(p)
    assert cfg.get("episode_cache_ttl_hours") == 6
    assert cfg.get("resolutions") == ["2160p", "1080p", "720p"]
    assert cfg.get("request_interval_seconds") == {"yts": 1.0, "eztv": 1.0, "nyaa": 2.0, "tpb": 2.0, "torrentio": 1.0}
    assert cfg.get("imdb_suggestion_base_url", "").startswith("https://")


def test_single_folder_storage_defaults():
    """R2.1: the default pipeline must leave exactly one folder per title."""
    assert DEFAULTS["import_mode"] == "move"
    assert DEFAULTS["seeding_policy"] == "remove_on_import"


def test_config_template_documents_single_folder_defaults():
    from arr.config.settings import CONFIG_TEMPLATE

    assert 'import_mode = "move"' in CONFIG_TEMPLATE
    assert 'seeding_policy = "remove_on_import"' in CONFIG_TEMPLATE


def test_save_config_round_trip(tmp_path):
    from arr.config.settings import Config, load_config, save_config

    p = tmp_path / "custom_config.toml"
    cfg = Config()
    cfg.values["download_root"] = "/custom/downloads"
    cfg.values["library_root"] = "/custom/library"
    cfg.values["import_mode"] = "move"
    cfg.values["max_concurrent_downloads"] = 5
    cfg.values["prefer_season_packs"] = False
    cfg.values["resolutions"] = ["1080p", "720p"]
    cfg.values["max_download_speed_kbps"] = 1000

    save_config(cfg, p)
    assert p.exists()

    loaded = load_config(p)
    assert loaded.get("download_root") == "/custom/downloads"
    assert loaded.get("library_root") == "/custom/library"
    assert loaded.get("import_mode") == "move"
    assert loaded.get("max_concurrent_downloads") == 5
    assert loaded.get("prefer_season_packs") is False
    assert loaded.get("resolutions") == ["1080p", "720p"]
    assert loaded.get("max_download_speed_kbps") == 1000


def test_new_indexer_defaults_load_from_clean_config():
    """1.1: tpb_base_url, torrentio_base_url, enabled_indexers, indexer_priority,
    and request_interval_seconds tpb/torrentio entries load with correct defaults."""
    from arr.config.settings import DEFAULTS

    assert DEFAULTS["tpb_base_url"] == "https://thepiratebay.org"
    assert DEFAULTS["torrentio_base_url"] == "http://localhost:8085"
    assert DEFAULTS["enabled_indexers"] == ["yts", "eztv", "nyaa", "tpb", "torrentio"]
    assert DEFAULTS["indexer_priority"] == ["yts", "eztv", "nyaa", "tpb", "torrentio"]
    riq = DEFAULTS["request_interval_seconds"]
    assert riq["tpb"] == 2.0
    assert riq["torrentio"] == 1.0


def test_new_defaults_in_config_template():
    """1.1: CONFIG_TEMPLATE documents all new keys."""
    from arr.config.settings import CONFIG_TEMPLATE

    assert 'tpb_base_url = "https://thepiratebay.org"' in CONFIG_TEMPLATE
    assert 'torrentio_base_url = "http://localhost:8085"' in CONFIG_TEMPLATE
    assert 'enabled_indexers = ["yts", "eztv", "nyaa", "tpb", "torrentio"]' in CONFIG_TEMPLATE
    assert 'indexer_priority = ["yts", "eztv", "nyaa", "tpb", "torrentio"]' in CONFIG_TEMPLATE
    assert "tpb = 2.0" in CONFIG_TEMPLATE
    assert "torrentio = 1.0" in CONFIG_TEMPLATE


def test_enabled_indexers_overridden_via_toml(tmp_path):
    """1.2: enabled_indexers can be overridden via TOML."""
    from arr.config.settings import load_config

    p = tmp_path / "config.toml"
    p.write_text(
        'enabled_indexers = ["yts", "tpb"]\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.get("enabled_indexers") == ["yts", "tpb"]


def test_indexer_priority_overridden_via_toml(tmp_path):
    """1.2: indexer_priority can be overridden via TOML."""
    from arr.config.settings import load_config

    p = tmp_path / "config.toml"
    p.write_text(
        'indexer_priority = ["tpb", "nyaa", "yts", "eztv", "torrentio"]\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.get("indexer_priority") == ["tpb", "nyaa", "yts", "eztv", "torrentio"]


def test_base_urls_overridden_via_toml(tmp_path):
    """1.2: base URLs can be overridden via TOML."""
    from arr.config.settings import load_config

    p = tmp_path / "config.toml"
    p.write_text(
        'tpb_base_url = "https://tpb.example.com"\n'
        'torrentio_base_url = "http://torrentio:8085"\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.get("tpb_base_url") == "https://tpb.example.com"
    assert cfg.get("torrentio_base_url") == "http://torrentio:8085"


def test_request_interval_seconds_overridden_via_toml(tmp_path):
    """1.2: request_interval_seconds can be overridden via TOML (table syntax)."""
    from arr.config.settings import load_config

    p = tmp_path / "config.toml"
    p.write_text(
        '[request_interval_seconds]\n'
        'yts = 0.5\n'
        'eztv = 0.8\n'
        'nyaa = 1.5\n'
        'tpb = 3.0\n'
        'torrentio = 0.5\n',
        encoding="utf-8",
    )
    cfg = load_config(p)
    assert cfg.get("request_interval_seconds") == {
        "yts": 0.5,
        "eztv": 0.8,
        "nyaa": 1.5,
        "tpb": 3.0,
        "torrentio": 0.5,
    }
