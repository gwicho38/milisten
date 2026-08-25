import json
import stat

import pytest

from milisten.web import launcher


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MILISTEN_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_daemon_state_round_trips():
    launcher.write_daemon_state({"pid": 42, "port": 8321, "token": "t", "url": "u"})
    assert launcher.read_daemon_state()["port"] == 8321


def test_daemon_file_is_owner_only():
    launcher.write_daemon_state({"pid": 1, "token": "secret"})
    assert mode(launcher.daemon_file()) == 0o600


def test_daemon_directory_is_owner_only():
    launcher.write_daemon_state({"pid": 1})
    assert mode(launcher.secure_home()) == 0o700


def test_a_loose_pre_existing_daemon_file_is_tightened():
    home = launcher.secure_home()
    stale = home / "daemon.json"
    stale.write_text("{}")
    stale.chmod(0o644)
    launcher.write_daemon_state({"pid": 7})
    assert mode(stale) == 0o600


def test_a_loose_pre_existing_log_is_tightened():
    launcher.secure_home()
    log = launcher.daemon_log()
    log.write_text("old line\n")
    log.chmod(0o644)
    import os

    os.close(launcher.open_private(log, append=True))
    assert mode(log) == 0o600


def test_appending_to_the_log_keeps_earlier_content():
    import os

    launcher.secure_home()
    log = launcher.daemon_log()
    log.write_text("first\n")
    with os.fdopen(launcher.open_private(log, append=True), "ab", buffering=0) as handle:
        handle.write(b"second\n")
    assert log.read_text() == "first\nsecond\n"


def test_writing_state_truncates_rather_than_appending():
    launcher.write_daemon_state({"pid": 1, "port": 1111})
    launcher.write_daemon_state({"pid": 2, "port": 2222})
    assert json.loads(launcher.daemon_file().read_text())["port"] == 2222


def test_clearing_state_removes_the_file():
    launcher.write_daemon_state({"pid": 1})
    launcher.clear_daemon_state()
    assert launcher.read_daemon_state() is None


def test_missing_state_reads_as_none():
    assert launcher.read_daemon_state() is None


def test_corrupt_state_reads_as_none():
    launcher.secure_home()
    launcher.daemon_file().write_text("{not json")
    assert launcher.read_daemon_state() is None


def test_launch_url_carries_the_token_on_loopback():
    url = launcher.build_launch_url(8321, "abc")
    assert url == "http://127.0.0.1:8321/?token=abc"


def test_minted_tokens_are_unique_and_long():
    tokens = {launcher.mint_token() for _ in range(50)}
    assert len(tokens) == 50
    assert all(len(t) >= 32 for t in tokens)


def test_picked_port_is_free_and_in_range():
    port = launcher.pick_free_port()
    assert 1024 < port <= 65535
    assert not launcher.port_is_open(port)


def test_a_dead_pid_clears_stale_state():
    launcher.write_daemon_state({"pid": 2**31 - 1, "url": "u"})
    assert launcher.live_daemon() is None
    assert launcher.read_daemon_state() is None


def test_a_live_pid_is_reported():
    import os

    launcher.write_daemon_state({"pid": os.getpid(), "url": "u"})
    assert launcher.live_daemon()["url"] == "u"


def test_child_entry_point_rejects_a_missing_port():
    from io import StringIO

    from milisten.web.__main__ import main

    assert main([], StringIO("tok\n")) == 1
    assert main(["notaport"], StringIO("tok\n")) == 1


def test_child_entry_point_requires_a_token_on_stdin():
    from io import StringIO

    from milisten.web.__main__ import main

    assert main(["8321"], StringIO("")) == 69
    assert main(["8321"], StringIO("   \n")) == 69


def test_child_entry_point_reads_the_token_from_stdin_not_argv(monkeypatch):
    from io import StringIO

    from milisten.web import __main__ as entry

    seen = {}
    monkeypatch.setattr(entry, "serve", lambda *a, **k: seen.update(args=a, kwargs=k))
    assert entry.main(["8321"], StringIO("s3cret\n")) == 0
    assert seen["args"] == (8321, "s3cret")
    assert seen["kwargs"] == {"open_browser": False, "announce": False}
