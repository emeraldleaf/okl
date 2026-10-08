"""`.okl/config.json` is owner-only whenever it holds the service token (#98).

`okl connect --token` stores the service bearer credential in that file. It was written
with default permissions, `-rw-r--r--` on macOS, so every local user could read it.
"""
import argparse
import os
import stat

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_a_config_holding_a_token_is_written_owner_only(tmp_path, monkeypatch):
    """A new config that holds the token is created owner-only."""
    from okl.client import save_config

    # ARRANGE / ACT — the documented flow writes the token
    monkeypatch.chdir(tmp_path)
    path = save_config({"repo": "r", "service_url": "https://okl.internal", "token": "s3cret"})

    # ASSERT — owner read/write only, and the token really is in it
    assert _mode(path) == 0o600
    assert "s3cret" in path.read_text()


def test_an_existing_readable_config_is_tightened_when_a_token_goes_in(tmp_path, monkeypatch):
    """os.open's mode applies only to a new file: a config an older okl wrote stays
    world-readable unless it is tightened explicitly."""
    from okl.client import save_config

    # ARRANGE — a config written before the token, readable by every local user
    monkeypatch.chdir(tmp_path)
    path = save_config({"repo": "r"})
    path.chmod(0o644)

    # ACT — `okl connect --token` rewrites it
    save_config({"repo": "r", "service_url": "https://okl.internal", "token": "s3cret"})

    # ASSERT
    assert _mode(path) == 0o600


def test_a_config_without_a_token_keeps_the_default_mode(tmp_path, monkeypatch):
    """Owner-only is for credentials. A config with no secret is written as before, so a
    teammate can still read a shared checkout's repo name and interests."""
    from okl.client import save_config

    monkeypatch.chdir(tmp_path)
    umask = os.umask(0)
    os.umask(umask)
    path = save_config({"repo": "r"})
    assert _mode(path) == 0o666 & ~umask


def test_okl_connect_with_a_token_leaves_an_owner_only_config(tmp_path, monkeypatch):
    """The command users run, not just the helper under it."""
    from okl.cli.install import cmd_connect

    monkeypatch.chdir(tmp_path)
    args = argparse.Namespace(url="https://okl.internal", token="s3cret")  # noqa: S106 -- a fake token is the test's subject
    assert cmd_connect(args) == 0
    assert _mode(tmp_path / ".okl" / "config.json") == 0o600
