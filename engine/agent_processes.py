"""
Agent Processes — Spawn, health-check, and clean up agent node subprocesses.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from engine.runtime import kill_processes_by_script_name

logger = logging.getLogger(__name__)

NODE_SCRIPT = Path(__file__).resolve().parent / "node.py"


def kill_old_nodes() -> None:
    killed = kill_processes_by_script_name(["node.py"])
    if killed:
        logger.info(f"Cleaned up {killed} stale node(s). Waiting for ports to free...")
        time.sleep(2)


async def start_nodes(
    agents: list[dict],
    run_dir: str,
    model_map: dict[str, str],
    rules: list[str],
    prompts_path: Path | str,
    schemas_path: Path | str,
) -> list[dict]:
    import asyncio

    processes: list[dict] = []
    os.makedirs(run_dir, exist_ok=True)

    for agent in agents:
        agent_dir = os.path.join(run_dir, agent["id"])
        os.makedirs(agent_dir, exist_ok=True)

        model_alias = agent.get("model", "smart-agent")
        resolved_model = model_map.get(model_alias, model_alias)

        agent_skills = agent.get("skills", [])
        cmd = [
            sys.executable,
            str(NODE_SCRIPT),
            "--port",
            str(agent["port"]),
            "--agent_id",
            agent["id"],
            "--soul",
            agent["soul"],
            "--model",
            resolved_model,
            "--output_dir",
            agent_dir,
            "--prompts_path",
            str(prompts_path),
            "--schemas_path",
            str(schemas_path),
            "--rules",
            json.dumps(rules),
            "--skills",
            ",".join(agent_skills),
        ]

        log_path = os.path.join(agent_dir, f"{agent['id']}_stderr.log")
        # Open + spawn off the event loop; to_thread returns the real file
        # handle / Popen object, so lifecycle calls (terminate/wait/kill) below
        # keep working unchanged.
        log_file = await asyncio.to_thread(open, log_path, "a", encoding="utf-8")
        env = os.environ.copy()
        proc = await asyncio.to_thread(
            subprocess.Popen, cmd, stdout=subprocess.DEVNULL, stderr=log_file, env=env
        )
        processes.append(
            {
                "id": agent["id"],
                "port": agent["port"],
                "proc": proc,
                "log_file": log_file,
            }
        )
        logger.info(
            f"Spawned {agent['id']} on port {agent['port']} (model={resolved_model})"
        )

    logger.info(
        "Waiting for nodes to start (LiteLLM import can take 10–15s on cold start)..."
    )
    await asyncio.sleep(10)

    async with httpx.AsyncClient(timeout=10.0) as client:
        max_rounds = 25
        for round_idx in range(max_rounds):
            failed: list[tuple[str, str]] = []
            for node in processes:
                nid, port = node["id"], node["port"]
                try:
                    resp = await client.get(f"http://127.0.0.1:{port}/health")
                    if resp.status_code != 200:
                        failed.append((nid, f"HTTP {resp.status_code}"))
                except Exception as e:
                    failed.append((nid, str(e)))

            if not failed:
                for node in processes:
                    logger.info(f"  {node['id']} healthy")
                break

            for nid, reason in failed:
                logger.warning(
                    f"  {nid} not ready ({reason}); round {round_idx + 1}/{max_rounds}"
                )
            await asyncio.sleep(2)
        else:
            for node in processes:
                try:
                    resp = await client.get(f"http://127.0.0.1:{node['port']}/health")
                    if resp.status_code == 200:
                        logger.info(f"  {node['id']} healthy")
                    else:
                        logger.error(
                            f"  {node['id']} still unhealthy: HTTP {resp.status_code}"
                        )
                except Exception as e:
                    logger.error(f"  {node['id']} health check failed: {e}")

    return processes


def cleanup_nodes(processes: list[dict]) -> None:
    for node in processes:
        try:
            node["proc"].terminate()
            node["proc"].wait(timeout=5)
        except Exception:
            try:
                node["proc"].kill()
            except Exception:
                pass
        try:
            node["log_file"].close()
        except Exception:
            pass
    logger.info(f"Cleaned up {len(processes)} node processes")
