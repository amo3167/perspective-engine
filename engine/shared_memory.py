"""
Shared Memory — Redis-backed context store for agent-to-agent communication.

Provides a shared state layer so agents can read/write meeting transcripts
and context without polluting their own conversation history.

When Redis is unavailable it falls back to a small **file-backed** store on the
local filesystem. This matters because the orchestrator and every meeting/debate
node run as separate OS processes: an in-process dict could never bridge them, so
the no-Redis "degraded" mode would silently drop every transcript. The file store
lives under a shared temp directory (override with ``PE_SHARED_MEM_DIR``) keyed by
a hash of the full key, so all processes on the host see the same values.
"""

import os
import json
import hashlib
import logging
import tempfile
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_DB = int(os.getenv("REDIS_DB", "3"))

_ENV_PREFIX = os.getenv("REDIS_KEY_PREFIX", "").strip()
PREFIX = f"{_ENV_PREFIX}:meeting:mem" if _ENV_PREFIX else "meeting:mem"
DEFAULT_TTL = 86400


def _fallback_dir() -> Path:
    """Directory backing the no-Redis fallback store (shared across processes)."""
    base = os.getenv("PE_SHARED_MEM_DIR") or os.path.join(
        tempfile.gettempdir(), "pe_shared_mem"
    )
    d = Path(base)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fallback_path(full_key: str) -> Path:
    digest = hashlib.sha256(full_key.encode("utf-8")).hexdigest()
    return _fallback_dir() / f"{digest}.json"


class SharedMemory:
    def __init__(self, redis_client=None, run_id: str = ""):
        self._redis = redis_client
        self._run_id = run_id

    @property
    def prefix(self) -> str:
        return PREFIX

    async def _get_redis(self):
        if self._redis is not None:
            return self._redis
        try:
            import redis.asyncio as aioredis

            self._redis = aioredis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                db=REDIS_DB,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info(
                f"SharedMemory connected to Redis {REDIS_HOST}:{REDIS_PORT}/db{REDIS_DB}"
            )
            return self._redis
        except Exception as e:
            logger.warning(
                f"Redis unavailable ({e}), using file-backed fallback at {_fallback_dir()}"
            )
            self._redis = None
            return None

    def _key(self, box_id: str, key: str) -> str:
        return f"{PREFIX}:{box_id}:{key}"

    # ── File-backed fallback (cross-process; used when Redis is down) ────────

    @staticmethod
    def _fallback_set(full_key: str, payload: str) -> None:
        path = _fallback_path(full_key)
        envelope = json.dumps({"k": full_key, "p": payload})
        # Atomic write so concurrent readers never see a partial file.
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(envelope)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    @staticmethod
    def _fallback_get(full_key: str) -> Optional[str]:
        path = _fallback_path(full_key)
        try:
            envelope = json.loads(path.read_text(encoding="utf-8"))
            return envelope.get("p")
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    @staticmethod
    def _fallback_delete(full_key: str) -> None:
        try:
            _fallback_path(full_key).unlink()
        except FileNotFoundError:
            pass

    async def set(
        self, box_id: str, key: str, value: Any, ttl: int = DEFAULT_TTL
    ) -> bool:
        full_key = self._key(box_id, key)
        payload = json.dumps(value, default=str)
        r = await self._get_redis()
        if r:
            try:
                await r.set(full_key, payload, ex=ttl)
                return True
            except Exception as e:
                logger.error(f"SharedMemory.set error: {e}")
        self._fallback_set(full_key, payload)
        return True

    async def get(self, box_id: str, key: str) -> Optional[Any]:
        full_key = self._key(box_id, key)
        r = await self._get_redis()
        if r:
            try:
                raw = await r.get(full_key)
                if raw is not None:
                    return json.loads(raw)
                # Redis reachable but key missing — fall through to the file
                # store in case it was written during a prior Redis outage.
            except Exception as e:
                logger.error(f"SharedMemory.get error: {e}")
        raw = self._fallback_get(full_key)
        return json.loads(raw) if raw is not None else None

    async def delete(self, box_id: str, key: str) -> bool:
        full_key = self._key(box_id, key)
        r = await self._get_redis()
        if r:
            try:
                await r.delete(full_key)
            except Exception:
                pass
        self._fallback_delete(full_key)
        return True

    async def set_shared(self, key: str, value: Any, ttl: int = DEFAULT_TTL) -> bool:
        return await self.set("shared", key, value, ttl)

    async def get_shared(self, key: str) -> Optional[Any]:
        return await self.get("shared", key)

    async def store_context_ref(self, data: Any, ttl: int = 3600) -> str:
        ref_id = f"ref:{uuid.uuid4().hex[:8]}"
        full_key = f"shared:{ref_id}"
        await self.set("shared", ref_id, data, ttl)
        return full_key

    async def get_context_ref(self, full_key: str) -> Optional[Any]:
        if ":" not in full_key:
            return None
        parts = full_key.split(":")
        if len(parts) < 3:
            return None
        namespace = parts[0]
        ref_key = ":".join(parts[1:])
        return await self.get(namespace, ref_key)

    async def health(self) -> dict:
        r = await self._get_redis()
        if r:
            try:
                await r.ping()
                return {"status": "healthy", "backend": "redis", "prefix": PREFIX}
            except Exception as e:
                return {"status": "degraded", "backend": "redis", "error": str(e)}
        keys = self._iter_fallback_keys()
        return {"status": "fallback", "backend": "file", "keys_count": len(keys)}

    @staticmethod
    def _iter_fallback_keys() -> list[str]:
        keys: list[str] = []
        for path in _fallback_dir().glob("*.json"):
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(envelope, dict) and "k" in envelope:
                    keys.append(envelope["k"])
            except (OSError, json.JSONDecodeError):
                continue
        return keys

    async def get_all_keys(self, pattern: str | None = None) -> list[str]:
        r = await self._get_redis()
        if r:
            try:
                search = pattern or f"{PREFIX}:*"
                keys: list[str] = []
                async for key in r.scan_iter(match=search, count=100):
                    keys.append(key)
                return keys
            except Exception as e:
                logger.error(f"SharedMemory.get_all_keys error: {e}")
        all_keys = self._iter_fallback_keys()
        if pattern:
            needle = pattern.rstrip("*")
            return [k for k in all_keys if k.startswith(needle)]
        return all_keys

    async def close(self):
        if self._redis:
            await self._redis.close()
