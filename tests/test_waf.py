"""Tests for the AWS WAF cookie provider (no real browser launched)."""

import json
import os
import time

import pytest

from arr.metadata.waf import WafCookieProvider, WafError


def _provider(tmp_path, ttl: float = 60.0) -> WafCookieProvider:
    return WafCookieProvider(cache_dir=tmp_path, ttl=ttl)


def _no_solve():
    def boom() -> dict[str, str]:
        raise AssertionError("solve was not expected")

    return boom


def test_cookies_empty_without_solving(tmp_path):
    p = _provider(tmp_path)
    p._solve = _no_solve()
    assert p.cookies() == {}


def test_force_solves_and_persists_to_disk(tmp_path):
    p = _provider(tmp_path)
    solved = {"aws-waf-token": "tok", "session-id": "1"}
    p._solve = lambda: solved
    assert p.cookies(force=True) == solved
    on_disk = json.loads((tmp_path / "imdb_cookies.json").read_text(encoding="utf-8"))
    assert on_disk == solved
    # A new provider instance reuses the disk cache without solving.
    p2 = _provider(tmp_path)
    p2._solve = _no_solve()
    assert p2.cookies() == solved


def test_stale_disk_triggers_resolve(tmp_path):
    p = _provider(tmp_path)
    path = tmp_path / "imdb_cookies.json"
    path.write_text(json.dumps({"aws-waf-token": "old"}), encoding="utf-8")
    mtime = time.time() - p.ttl - 10
    os.utime(path, (mtime, mtime))
    p._solve = lambda: {"aws-waf-token": "new"}
    assert p.cookies(force=True)["aws-waf-token"] == "new"


def test_disk_without_token_is_ignored(tmp_path):
    p = _provider(tmp_path)
    (tmp_path / "imdb_cookies.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    p._solve = _no_solve()
    assert p.cookies() == {}


def test_solve_failure_raises_waf_error(tmp_path):
    p = _provider(tmp_path)

    def boom() -> dict[str, str]:
        raise RuntimeError("chromium missing")

    p._solve = boom
    with pytest.raises(WafError):
        p.cookies(force=True)
