"""Shared pytest fixtures and import paths for the perspective-engine suite."""

import sys
from pathlib import Path

import pytest

PE_ROOT = Path(__file__).resolve().parent.parent
_EXTRA_PATHS = [
    PE_ROOT,
    PE_ROOT / "patterns" / "customer_feedback" / "scripts",
    PE_ROOT / "patterns" / "debate" / "scripts",
]
for _p in _EXTRA_PATHS:
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


@pytest.fixture(autouse=True)
def isolate_shared_mem(tmp_path, monkeypatch):
    """Point the SharedMemory file-fallback store at a per-test temp dir."""
    monkeypatch.setenv("PE_SHARED_MEM_DIR", str(tmp_path / "pe_shared_mem"))
    yield
