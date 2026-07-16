"""node.py async context helpers (read/append transcript) with a fake store."""

import asyncio

import engine.node as node


def _run(coro):
    return asyncio.run(coro)


class _FakeMem:
    def __init__(self, data):
        self.data = data
        self.saved = []

    async def get_context_ref(self, ref):
        return self.data

    async def set(self, ns, key, val):
        self.saved.append((ns, key, val))


def test_read_helpers_return_stored_fields(monkeypatch):
    fm = _FakeMem(
        {"transcript": [{"x": 1}], "domain_handbook": "HB", "context_dir": "CD"}
    )
    monkeypatch.setattr(node, "mem", fm)
    assert _run(node._read_transcript("a:b")) == [{"x": 1}]
    assert _run(node._read_handbook("a:b")) == "HB"
    assert _run(node._read_context_dir("a:b")) == "CD"


def test_read_helpers_tolerate_missing_context(monkeypatch):
    monkeypatch.setattr(node, "mem", _FakeMem(None))
    assert _run(node._read_transcript("a:b")) == []
    assert _run(node._read_handbook("a:b")) == ""
    assert _run(node._read_context_dir("a:b")) == ""


def test_append_to_transcript_writes_back(monkeypatch):
    fm = _FakeMem({"transcript": [{"x": 1}]})
    monkeypatch.setattr(node, "mem", fm)
    _run(node._append_to_transcript("ns:key:sub", {"y": 2}))
    assert fm.saved, "expected a write-back via mem.set"
    ns, key, data = fm.saved[0]
    assert ns == "ns" and key == "key:sub"
    assert data["transcript"][-1] == {"y": 2}


def test_append_to_transcript_initializes_when_empty(monkeypatch):
    fm = _FakeMem(None)
    monkeypatch.setattr(node, "mem", fm)
    _run(node._append_to_transcript("ns:key", {"y": 9}))
    _ns, _key, data = fm.saved[0]
    assert data["transcript"] == [{"y": 9}]
