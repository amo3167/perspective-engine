"""SharedMemory file-backed fallback — findings [3] and [4]."""

import asyncio
import json

from engine.shared_memory import SharedMemory


def _run(coro):
    return asyncio.run(coro)


def _force_no_redis(monkeypatch):
    async def no_redis(self):
        return None

    monkeypatch.setattr(SharedMemory, "_get_redis", no_redis)


def test_fallback_bridges_separate_instances(monkeypatch):
    # Finding [3]: nodes run as separate processes, so the no-Redis fallback must
    # be visible across independent SharedMemory instances, not a per-process dict.
    _force_no_redis(monkeypatch)
    writer = SharedMemory()
    reader = SharedMemory()

    _run(writer.set("shared", "ref:abc", {"transcript": [1, 2, 3]}))
    assert _run(reader.get("shared", "ref:abc")) == {"transcript": [1, 2, 3]}


def test_context_ref_roundtrip_without_redis(monkeypatch):
    _force_no_redis(monkeypatch)
    writer = SharedMemory()
    reader = SharedMemory()

    ref = _run(writer.store_context_ref({"transcript": ["hello"]}))
    assert _run(reader.get_context_ref(ref)) == {"transcript": ["hello"]}


def test_get_consults_fallback_on_redis_miss():
    # Finding [4]: Redis reachable but the key is absent — get() must fall through
    # to the file fallback instead of returning None outright.
    class FakeRedis:
        async def ping(self):
            return True

        async def get(self, key):
            return None  # always a miss

        async def set(self, key, val, ex=None):
            return True

    sm = SharedMemory(redis_client=FakeRedis())
    full_key = sm._key("shared", "ref:xyz")
    SharedMemory._fallback_set(full_key, json.dumps({"v": 42}))

    assert _run(sm.get("shared", "ref:xyz")) == {"v": 42}


def test_delete_clears_fallback(monkeypatch):
    _force_no_redis(monkeypatch)
    sm = SharedMemory()
    _run(sm.set("box", "k", {"v": 1}))
    assert _run(sm.get("box", "k")) == {"v": 1}

    _run(sm.delete("box", "k"))
    assert _run(sm.get("box", "k")) is None


def test_health_reports_file_backend(monkeypatch):
    _force_no_redis(monkeypatch)
    sm = SharedMemory()
    _run(sm.set("box", "k", {"v": 1}))
    health = _run(sm.health())
    assert health["status"] == "fallback"
    assert health["backend"] == "file"
    assert health["keys_count"] >= 1
