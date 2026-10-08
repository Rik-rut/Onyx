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
