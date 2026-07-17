"""engine.runtime — SSL policy, process kill, and script spawn helpers."""

import subprocess
import sys

import psutil
import pytest

import engine.runtime as runtime
from engine.runtime import (
    bootstrap_litellm,
    kill_processes_by_script_name,
    spawn_python_script,
    ssl_verify_enabled,
)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("yes", True),
        ("anything-else", True),
        ("false", False),
        ("False", False),
        ("0", False),
        ("no", False),
        ("  no  ", False),
    ],
)
def test_ssl_verify_enabled_reads_env(monkeypatch, value, expected):
    monkeypatch.setenv("LITELLM_SSL_VERIFY", value)
    assert ssl_verify_enabled() is expected


def test_ssl_verify_enabled_defaults_true(monkeypatch):
    monkeypatch.delenv("LITELLM_SSL_VERIFY", raising=False)
    assert ssl_verify_enabled() is True


def test_bootstrap_litellm_applies_settings(monkeypatch):
    monkeypatch.delenv("LITELLM_SSL_VERIFY", raising=False)
    bootstrap_litellm()
    import litellm

    assert litellm.drop_params is True
    assert litellm.ssl_verify is True


class _FakeProc:
    def __init__(self, pid, cmdline, raise_on_kill=False):
        self.info = {"pid": pid, "cmdline": cmdline}
        self.killed = False
        self._raise = raise_on_kill

    def kill(self):
        if self._raise:
            raise psutil.NoSuchProcess(self.info["pid"])
        self.killed = True


def test_kill_processes_matches_skips_self_and_survives_errors(monkeypatch):
    import os

    me = os.getpid()
    match = _FakeProc(9999, ["python", "/x/node.py", "--port", "9001"])
    myself = _FakeProc(me, ["python", "node.py"])  # must be skipped
    other = _FakeProc(8888, ["bash", "unrelated.sh"])
    empty = _FakeProc(7777, None)  # no cmdline
    gone = _FakeProc(6666, ["python", "node.py"], raise_on_kill=True)

    procs = [match, myself, other, empty, gone]
    monkeypatch.setattr(runtime.psutil, "process_iter", lambda fields: procs)

    killed = kill_processes_by_script_name(["node.py"])

    assert killed == 1  # only `match` (self skipped, gone raised, others no match)
    assert match.killed is True
    assert myself.killed is False
    assert other.killed is False


def test_spawn_python_script_builds_command(monkeypatch, tmp_path):
    captured = {}

    class FakePopen:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs

    monkeypatch.setattr(runtime.subprocess, "Popen", FakePopen)

    log_path = tmp_path / "out.log"
    spawn_python_script(
        "engine/node.py", ["--port", "9001"], cwd=tmp_path, log_path=log_path
    )

    assert captured["cmd"][0] == sys.executable
    assert "engine/node.py" in captured["cmd"]
    assert captured["cmd"][-2:] == ["--port", "9001"]
    assert captured["kwargs"]["stdout"] == subprocess.DEVNULL
    assert log_path.exists()  # a log file was opened for stderr
