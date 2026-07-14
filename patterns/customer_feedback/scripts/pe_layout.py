"""Perspective-engine + monorepo roots for customer_feedback scripts."""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent


def roots() -> tuple[Path, Path]:
    """Return (perspective_engine_root, auto_bbs_repo_root)."""
    pe = _SCRIPT_DIR.parents[2]
    repo = _SCRIPT_DIR.parents[3]
    return pe, repo


def ensure_sys_path() -> tuple[Path, Path]:
    pe, repo = roots()
    for p in (pe, repo):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
    return pe, repo


def load_dotenv_layers() -> None:
    from dotenv import load_dotenv

    pe, repo = roots()
    load_dotenv(pe / ".env")
    gateway = repo / "agent_gateway" / ".env"
    if gateway.is_file():
        load_dotenv(gateway)
