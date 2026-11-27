"""The docker-compose.yml must import cleanly into ZimaOS.

ZimaOS reads a top-level ``x-casaos`` block (service-level blocks are legacy),
static port mappings, and per-library volumes. ``docker`` is not available in
the test environment, so the file is validated by parsing it as YAML.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


def load_compose() -> dict:
    return yaml.safe_load(COMPOSE_PATH.read_text(encoding="utf-8"))


def test_project_is_named_onyx() -> None:
    compose = load_compose()
    assert compose["name"] == "onyx"
    assert "onyx" in compose["services"]


def test_top_level_casaos_block_has_required_fields() -> None:
    casaos = load_compose()["x-casaos"]
    for field in (
        "id",
        "main",
        "index",
        "port_map",
        "scheme",
        "icon",
        "title",
        "tagline",
        "description",
        "author",
        "developer",
        "category",
        "architectures",
        "version",
    ):
        assert field in casaos, f"missing x-casaos field: {field}"
    assert casaos["id"] == "com.onyx.media"
    assert casaos["main"] == "onyx"
    assert casaos["index"] == "/"
    assert casaos["port_map"] == "3698"
    assert casaos["scheme"] == "http"
    assert casaos["version"] == "0.1.1"
    assert casaos["category"] == "Media"
    assert casaos["architectures"] == ["amd64", "arm64"]


def test_locale_fields_use_en_us_objects() -> None:
    casaos = load_compose()["x-casaos"]
    for field in ("title", "tagline", "description"):
        locale = casaos[field]
        assert isinstance(locale, dict)
        assert "en_US" in locale
        assert locale["en_US"]


def test_icon_points_at_the_repo_asset() -> None:
    icon = load_compose()["x-casaos"]["icon"]
    assert icon.startswith("https://raw.githubusercontent.com/")
    assert icon.endswith("/master/assets/onyx.svg")
    # The asset must exist in the repo (the URL path mirrors it).
    assert (REPO_ROOT / "assets" / "onyx.svg").is_file()


def test_no_service_level_casaos_blocks() -> None:
    compose = load_compose()
    for name, service in compose["services"].items():
        assert "x-casaos" not in service, f"legacy service-level x-casaos on {name}"


def test_ports_are_static() -> None:
    ports = load_compose()["services"]["onyx"]["ports"]
    assert ports == ["3698:3698", "9091:9091", "51413:51413", "51413:51413/udp"]


def test_library_volumes_use_zimaos_import_paths() -> None:
    volumes = load_compose()["services"]["onyx"]["volumes"]
    assert volumes == [
        "/DATA/AppData/onyx/config:/config",
        "/DATA/AppData/onyx/downloads/movies:/downloads/movies",
        "/DATA/AppData/onyx/downloads/tv-shows:/downloads/tv-shows",
    ]
