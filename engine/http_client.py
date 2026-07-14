"""
HTTP Client — Typed wrappers for orchestrator → agent node communication.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BACKEND_URL = os.environ.get("PERSPECTIVE_ENGINE_BACKEND_URL", "http://127.0.0.1:8100")


async def notify_backend(payload: dict[str, Any]) -> None:
    url = f"{BACKEND_URL}/api/meeting/broadcast"
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(url, json=payload, timeout=2.0)
            logger.debug(
                "notify_backend %s → %s", payload.get("meeting_type"), resp.status_code
            )
        except Exception as exc:
            logger.debug("notify_backend failed: %s", exc)


async def trigger_meeting_turn(
    port: int,
    context_ref: str,
    meeting_id: str,
    phase: int,
    directed_prompt: str = "",
    expected_message_type: str = "",
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=300.0) as client:
        try:
            resp = await client.post(
                f"http://127.0.0.1:{port}/meeting_turn",
                json={
                    "context_ref": context_ref,
                    "meeting_id": meeting_id,
                    "phase": phase,
                    "directed_prompt": directed_prompt,
                    "expected_message_type": expected_message_type,
                },
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to trigger meeting_turn on port {port}: {e}")
    return {"status": "error"}


async def trigger_facilitate(
    port: int,
    context_ref: str,
    meeting_id: str,
    elapsed: float,
    time_limit: float,
    speaker_history: list[str],
    silent_agents: list[str],
    proposal_sections: list[str],
    participant_ids: list[str] | None = None,
    author_id: str = "",
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            resp = await client.post(
                f"http://127.0.0.1:{port}/facilitate",
                json={
                    "context_ref": context_ref,
                    "meeting_id": meeting_id,
                    "elapsed_seconds": elapsed,
                    "time_limit_seconds": time_limit,
                    "speaker_history": speaker_history,
                    "silent_agents": silent_agents,
                    "proposal_sections": proposal_sections,
                    "participant_ids": participant_ids or [],
                    "author_id": author_id,
                },
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Failed to trigger facilitate on port {port}: {e}")
    return {"decision": "END_DISCUSSION", "status": "error"}


async def trigger_relevance_check(
    port: int,
    context_ref: str,
    meeting_id: str,
    nomination_context: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            resp = await client.post(
                f"http://127.0.0.1:{port}/relevance_check",
                json={
                    "context_ref": context_ref,
                    "meeting_id": meeting_id,
                    "nomination_context": nomination_context,
                },
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Relevance check failed on port {port}: {e}")
    return {"decision": "PASS", "agent_id": "unknown"}
