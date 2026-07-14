import sys
import os
import asyncio
import logging

PE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PE_ROOT not in sys.path:
    sys.path.insert(0, PE_ROOT)

from engine.shared_memory import SharedMemory
from engine.runtime import kill_processes_by_script_name

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("cleanup_debate")

PREFIX = "meeting:mem:"


def _parse_redis_key(full_key: str) -> tuple[str, str] | None:
    if not full_key.startswith(PREFIX):
        return None
    remainder = full_key[len(PREFIX) :]
    if ":" not in remainder:
        return None
    box_id, key = remainder.split(":", 1)
    return box_id, key


async def kill_node_processes():
    logger.info("Searching for debate processes...")
    killed_count = kill_processes_by_script_name(
        ["debate_node.py", "debate_orchestrator.py"]
    )
    logger.info(f"Terminated {killed_count} process(es).")


async def clean_redis_keys():
    logger.info("Cleaning debate keys from shared memory (Redis)...")
    mem = SharedMemory()
    removed_count = 0
    keys = await mem.get_all_keys(pattern=f"{PREFIX}shared:ref:*")
    for full_key in keys:
        parsed = _parse_redis_key(full_key)
        if not parsed:
            continue
        box_id, key_id = parsed
        await mem.delete(box_id, key_id)
        removed_count += 1
    logger.info(f"Removed {removed_count} context ref key(s).")
    await mem.delete("shared", "global_rules")
    await mem.delete("shared", "current_debate_session")


async def main():
    print("--- DEBATE PATTERN CLEANUP ---")
    await kill_node_processes()
    await clean_redis_keys()
    print("Cleanup complete.")


if __name__ == "__main__":
    asyncio.run(main())
