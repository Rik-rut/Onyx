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
    assert cfg.get("request_interval_seconds") == {"yts": 1.0, "eztv": 1.0, "nyaa": 2.0}
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
