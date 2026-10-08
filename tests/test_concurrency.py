"""Tests for the transmission concurrency planner and status helpers."""

from arr.transmission.process import (
    DOWNLOAD,
    SEED,
    STOPPED,
    active_count,
    is_active_torrent,
    is_complete_torrent,
    plan_slots,
)


def t(status=0, percent=0.0):
    return {"status": status, "percentDone": percent}


def test_plan_slots_under_limit_all_start():
    # 0 active, limit 3, 2 new -> both start (paused False)
    assert plan_slots(0, 3, 2) == [False, False]


def test_plan_slots_at_limit_all_queued():
    assert plan_slots(3, 3, 2) == [True, True]


def test_plan_slots_partial():
    # 1 active, limit 3, 4 new -> first 2 start, last 2 queue
    assert plan_slots(1, 3, 4) == [False, False, True, True]


def test_plan_slots_zero_count():
    assert plan_slots(5, 3, 0) == []


def test_plan_slots_nonpositive_limit_clamped():
    assert plan_slots(0, 0, 2) == [False, True]


def test_is_active_and_complete():
    assert not is_active_torrent(t(STOPPED, 0.0))
    assert is_active_torrent(t(DOWNLOAD, 0.5))
    assert not is_active_torrent(t(SEED, 1.0))
    assert is_complete_torrent(t(SEED, 1.0))
    assert is_complete_torrent(t(DOWNLOAD, 1.0))
    assert not is_complete_torrent(t(DOWNLOAD, 0.9))


def test_active_count_mixed():
    torrents = [t(DOWNLOAD, 0.3), t(STOPPED, 0.0), t(DOWNLOAD, 0.99), t(SEED, 1.0)]
    assert active_count(torrents) == 2


def test_port_in_use_detects_listener():
    import socket

    from arr.transmission.process import port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        assert port_in_use(port) is True
    # after close, port is free
    assert port_in_use(port) is False


def test_port_in_use_free_port():
    from arr.transmission.process import port_in_use

    assert port_in_use(1) is False


def test_find_stale_lock_none_by_default(tmp_path, monkeypatch):
    from arr.transmission import process

    monkeypatch.setattr(process, "lock_file_paths", lambda: [tmp_path / "lock"])
    assert process.find_stale_lock() is None


def test_find_stale_lock_detects_existing(tmp_path, monkeypatch):
    from arr.transmission import process

    lock = tmp_path / "transmission-daemon" / "lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("x")
    monkeypatch.setattr(
        process, "lock_file_paths", lambda: [lock, tmp_path / "other" / "lock"]
    )
    assert process.find_stale_lock() == lock
