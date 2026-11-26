"""AuthStore: default-account seeding, hashing, verification, credential change."""

from __future__ import annotations

from pathlib import Path

from arr.auth import DEFAULT_USERNAME, AuthStore


def test_first_access_seeds_default_account(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.toml")
    store.load()

    assert store.path.exists()
    assert store.username == DEFAULT_USERNAME
    assert store.must_change_credentials is True
    assert store.verify("admin", "1234")


def test_seeded_credentials_are_never_plain_text(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.toml")
    store.load()

    content = store.path.read_text(encoding="utf-8")
    assert "1234" not in content
    assert "pbkdf2_sha256$" in content


def test_verify_success_and_failure(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.toml")
    store.load()

    assert store.verify("admin", "1234") is True
    assert store.verify("admin", "nope") is False
    assert store.verify("someone", "1234") is False
    assert store.verify("", "1234") is False


def test_change_credentials_clears_flag_and_rotates_password(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.toml")
    store.load()
    assert store.must_change_credentials is True

    store.change_credentials("onyx", "hunter2")
    store.load()  # re-read from disk

    assert store.must_change_credentials is False
    assert store.username == "onyx"
    assert store.verify("onyx", "hunter2") is True
    assert store.verify("admin", "1234") is False


def test_change_credentials_stores_no_plain_text(tmp_path: Path) -> None:
    store = AuthStore(tmp_path / "auth.toml")
    store.load()
    store.change_credentials("onyx", "hunter2")

    content = store.path.read_text(encoding="utf-8")
    assert "hunter2" not in content
    assert "pbkdf2_sha256$" in content


def test_change_credentials_accepts_simple_password(tmp_path: Path) -> None:
    """No complexity rules: any non-empty password is accepted."""
    store = AuthStore(tmp_path / "auth.toml")
    store.load()
    store.change_credentials("a", "b")
    store.load()
    assert store.verify("a", "b") is True
