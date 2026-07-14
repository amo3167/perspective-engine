"""
Runtime Support — Shared helpers for spawning scripts, health-checking HTTP endpoints,
and bootstrapping LiteLLM. Used by engine/ and patterns/.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import psutil

logger = logging.getLogger(__name__)


def spawn_python_script(
    script: str | Path,
    args: list[str],
    cwd: str | Path | None = None,
    log_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.Popen:
    cmd = [sys.executable, str(script), *args]
    stderr_target: Any = subprocess.DEVNULL
    log_file = None
    if log_path:
        log_file = open(str(log_path), "a", encoding="utf-8")
        stderr_target = log_file
    run_env = env or os.environ.copy()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=stderr_target,
        cwd=str(cwd) if cwd else None,
        env=run_env,
    )
    return proc


async def wait_for_http_health(
    urls: list[str],
    timeout: float = 60.0,
    interval: float = 2.0,
) -> dict[str, bool]:
    """Poll GET endpoints until healthy or timeout. Returns {url: is_healthy}."""
    results = {u: False for u in urls}
    deadline = asyncio.get_event_loop().time() + timeout

    async with httpx.AsyncClient(timeout=10.0) as client:
        while asyncio.get_event_loop().time() < deadline:
            pending = [u for u, ok in results.items() if not ok]
            if not pending:
                break
            for url in pending:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        results[url] = True
                except Exception:
                    pass
            if all(results.values()):
                break
            await asyncio.sleep(interval)

    return results


def kill_processes_by_script_name(
    script_names: list[str],
    exclude_pid: int | None = None,
) -> int:
    killed = 0
    my_pid = exclude_pid or os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] == my_pid:
                continue
            cmd = proc.info.get("cmdline")
            if not cmd:
                continue
            cmd_str = " ".join(cmd)
            if any(name in cmd_str for name in script_names):
                logger.info(
                    f"Killing PID {proc.info['pid']} ({cmd_str.split('/')[-1][:80]})"
                )
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return killed


def ssl_verify_enabled() -> bool:
    """Whether outbound TLS certificates should be verified.

    Secure by default. Set ``LITELLM_SSL_VERIFY=false`` (or 0/no) only when a
    trusted man-in-the-middle proxy with a self-signed cert is required — this
    disables certificate validation for all LLM/credential traffic.
    """
    return os.getenv("LITELLM_SSL_VERIFY", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    )


def bootstrap_litellm() -> None:
    """Apply standard LiteLLM settings from env."""
    import litellm

    litellm.drop_params = True
    litellm.ssl_verify = ssl_verify_enabled()
