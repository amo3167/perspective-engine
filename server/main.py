"""
Perspective Engine — Standalone Meeting Server

Lightweight FastAPI backend that:
  - Lists available meeting packs from packs/
  - Starts meetings by spawning engine.orchestrator as a subprocess
  - Receives real-time events from the orchestrator via POST /api/meeting/broadcast
  - Relays events to connected browsers via WebSocket

Run:
    python -m server.main
"""

from __future__ import annotations

import json
import logging
import os
import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pe-server")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PACKS_DIR = PROJECT_ROOT / "packs"

app = FastAPI(title="Perspective Engine", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── In-process state (no external DB needed) ─────────────────────────────

meeting_state: dict[str, Any] = {
    "status": "idle",
    "transcript": [],
    "topic": "",
    "phase": 0,
}
debate_state: dict[str, Any] = {"status": "idle", "turns": [], "topic": ""}
feedback_state: dict[str, Any] = {"status": "idle", "steps": [], "events": []}
ws_clients: set[WebSocket] = set()


def autobbs_root() -> Path:
    env = os.environ.get("AUTOBBS_ROOT")
    if env:
        return Path(env).resolve()
    parent = PROJECT_ROOT.parent
    if (parent / "backend").is_dir() and (parent / ".agent").is_dir():
        return parent
    return parent


def pe_public_base() -> str:
    port = os.environ.get("PE_SERVER_PORT", "8100")
    return os.environ.get("PE_PUBLIC_URL", f"http://127.0.0.1:{port}")


def _monorepo_python() -> str:
    """Return the AutoBBS monorepo venv Python (debate/feedback scripts need its deps)."""
    venv_py = autobbs_root() / ".venv" / "bin" / "python"
    if venv_py.is_file():
        return str(venv_py)
    return sys.executable


async def ws_send(event_type: str, payload: dict[str, Any]) -> None:
    message = {
        "type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **payload,
    }
    dead: list[WebSocket] = []
    for ws in ws_clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        ws_clients.discard(ws)


# ── WebSocket ─────────────────────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    logger.info("WebSocket client connected (%d total)", len(ws_clients))
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data) if data else {}
            if msg.get("type") == "ping":
                await ws.send_json({"type": "pong", "timestamp": msg.get("timestamp")})
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        ws_clients.discard(ws)
        logger.info("WebSocket client disconnected (%d remaining)", len(ws_clients))


# ── REST API ──────────────────────────────────────────────────────────────

ROLE_ICON_MAP = {
    "moderator": "mdi-account-tie",
    "author": "mdi-pencil-box",
    "gatekeeper": "mdi-pillar",
    "decision_maker": "mdi-gavel",
    "risk_guardian": "mdi-shield-check",
    "ux_advocate": "mdi-account-heart",
    "ops_guardian": "mdi-server-security",
    "culture_guardian": "mdi-account-group",
    "messaging_strategist": "mdi-bullhorn",
    "devils_advocate": "mdi-fire",
    "senior_strategist": "mdi-lightbulb",
    "product_strategist": "mdi-package-variant",
    "security_auditor": "mdi-shield-lock",
    "final_reviewer": "mdi-shield-star",
}
TEAM_COLORS = [
    "#6D4C41",
    "#1565C0",
    "#6A1B9A",
    "#E65100",
    "#00838F",
    "#2E7D32",
    "#AD1457",
    "#4527A0",
]


@app.get("/api/meeting/packs")
async def list_packs():
    packs: list[dict] = []
    if not PACKS_DIR.is_dir():
        return packs
    for pack_path in sorted(PACKS_DIR.iterdir()):
        template_path = pack_path / "meeting_template.json"
        profiles_path = pack_path / "profiles.json"
        if not pack_path.is_dir() or not template_path.is_file():
            continue
        try:
            tmpl = json.loads(template_path.read_text())
            phases = [
                {"id": p.get("phase_number"), "label": p.get("label", "")}
                for p in tmpl.get("phases", [])
            ]
            agents: list[dict] = []
            if profiles_path.is_file():
                prof = json.loads(profiles_path.read_text())
                for i, a in enumerate(prof.get("agents", [])):
                    aid = a.get("id")
                    if not aid:
                        continue  # skip a malformed agent rather than dropping the whole pack
                    role = a.get("role", "")
                    short = a.get("short_name") or " ".join(
                        w.capitalize() for w in aid.replace("-", " ").split()
                    )
                    agents.append(
                        {
                            "id": aid,
                            "shortName": short,
                            "role": role.replace("_", " ").title(),
                            "icon": ROLE_ICON_MAP.get(role, "mdi-account"),
                            "color": TEAM_COLORS[i % len(TEAM_COLORS)],
                            "soul": a.get("soul", ""),
                        }
                    )
            packs.append(
                {
                    "name": pack_path.name,
                    "path": str(pack_path),
                    "description": tmpl.get("description", ""),
                    "template_name": tmpl.get("template_name", pack_path.name),
                    "phases": phases,
                    "agents": agents,
                }
            )
        except Exception:
            logger.exception("Failed to load pack %s", pack_path.name)
    return packs


@app.post("/api/meeting/broadcast")
async def receive_broadcast(payload: dict):
    global meeting_state
    mt = payload.get("meeting_type", "")
    mid = payload.get("meeting_id", "")

    if mt == "meeting_start":
        meeting_state = {
            "status": "active",
            "meeting_id": mid,
            "topic": payload.get("topic", ""),
            "agents": payload.get("agents", []),
            "phase": 1,
            "transcript": [],
            "start_time": payload.get("timestamp"),
        }
    elif mt == "phase_complete":
        # `.get(key, default)` returns None (not the default) when the key is
        # present with a null value, so coerce explicitly before the +1.
        meeting_state["phase"] = (payload.get("phase") or 0) + 1
        if payload.get("architect_decision"):
            meeting_state["architect_decision"] = payload["architect_decision"]
    elif mt == "meeting_turn":
        meeting_state.setdefault("transcript", []).append(
            {
                "from_agent": payload.get("from_agent"),
                "message_type": payload.get("message_type"),
                "content": payload.get("content"),
                "phase": payload.get("phase"),
                "timestamp": payload.get("timestamp"),
            }
        )
    elif mt == "facilitator_decision":
        meeting_state["facilitator_decision"] = payload.get("decision")
        meeting_state["facilitator_targets"] = payload.get("targets", [])
    elif mt == "meeting_finish":
        meeting_state["status"] = "finished"
        meeting_state["finish_time"] = payload.get("timestamp")
        meeting_state["elapsed_seconds"] = payload.get("elapsed_seconds")
        meeting_state["architect_decision"] = payload.get("architect_decision")
        meeting_state["total_turns"] = payload.get("total_turns")

    await ws_send("meeting_update", payload)
    return {"status": "ok"}


@app.get("/api/meeting/current")
async def get_current_state():
    return meeting_state


@app.post("/api/meeting/start")
async def start_meeting(payload: dict | None = None):
    global meeting_state
    body = payload or {}
    topic = body.get("topic", "")
    pack_path = body.get("meeting_pack", "")

    if not topic:
        return {"status": "error", "message": "topic is required"}
    if not pack_path or not Path(pack_path).is_dir():
        return {"status": "error", "message": f"Invalid meeting_pack path: {pack_path}"}

    cmd = [
        sys.executable,
        "-m",
        "engine.orchestrator",
        "--topic",
        topic,
        "--meeting-pack",
        pack_path,
    ]

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "meeting_arena.log"

    ts = datetime.now(timezone.utc).isoformat()
    banner = f"\n{'=' * 60}\n  Meeting — {ts}\n  topic={topic}\n  pack={pack_path}\n{'=' * 60}\n"

    log_f = await asyncio.to_thread(open, log_path, "a", encoding="utf-8")
    log_f.write(banner)
    log_f.flush()

    popen_kw: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT),
        "stdout": log_f,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform != "win32":
        popen_kw["start_new_session"] = True

    await asyncio.to_thread(subprocess.Popen, cmd, **popen_kw)
    logger.info("Meeting subprocess started: %s", " ".join(cmd[:6]))

    meeting_state = {"status": "starting", "topic": topic, "transcript": [], "phase": 0}
    return {"status": "ok", "message": "Meeting started", "log_file": str(log_path)}


@app.post("/api/meeting/reset")
async def reset_meeting():
    global meeting_state
    meeting_state = {"status": "idle", "transcript": [], "topic": "", "phase": 0}
    return {"status": "idle"}


# ── Debate (same paths as AutoBBS /api/monitor/debate/*) ───────────────────


@app.post("/api/monitor/debate/broadcast")
async def debate_broadcast(payload: dict):
    global debate_state
    d_type = payload.get("debate_type") or payload.get("type")

    if d_type == "debate_start":
        debate_state = {
            "topic": payload.get("topic"),
            "context_ref": payload.get("context_ref"),
            "turns": [],
            "status": "active",
            "start_time": payload.get("timestamp"),
        }
    elif d_type == "debate_turn":
        state = debate_state
        if state:
            for k in (
                "active_phase",
                "active_agents",
                "insight_team",
                "insight_captain",
            ):
                state.pop(k, None)
        turn = payload.get("turn") or {
            "agent_id": payload.get("agent_id"),
            "content": payload.get("content"),
            "round": payload.get("round"),
            "turn_index": payload.get("turn_index"),
            "timestamp": payload.get("timestamp"),
        }
        if turn.get("content"):
            state.setdefault("turns", []).append(turn)
    elif d_type == "debate_insight":
        state = debate_state
        if state:
            state["active_phase"] = payload.get("phase")
            state["active_agents"] = payload.get("agents", [])
            state["insight_team"] = payload.get("team")
            state["insight_captain"] = payload.get("captain")
    elif d_type == "debate_finish":
        state = debate_state
        if state:
            state["status"] = "finished"
            state["finish_time"] = payload.get("timestamp")
            for k in (
                "active_phase",
                "active_agents",
                "insight_team",
                "insight_captain",
            ):
                state.pop(k, None)

    await ws_send("debate_update", payload)
    return {"status": "ok"}


@app.get("/api/monitor/debate/current")
async def debate_current():
    if not debate_state.get("topic") and debate_state.get("status") != "active":
        return {"status": "idle", "turns": [], "topic": ""}
    return debate_state


def _resolve_debate_run() -> tuple[Path, Path, Path, str, str] | None:
    """(script, cleanup, cwd, python, broadcast_env_var) for the debate runner.

    Prefer the bundled patterns/debate scripts (which run standalone and read
    PERSPECTIVE_ENGINE_DEBATE_BACKEND_URL); fall back to the AutoBBS monorepo
    skill. Returns None when no runnable debate script exists.
    """
    bundled_dir = PROJECT_ROOT / "patterns" / "debate" / "scripts"
    bundled = bundled_dir / "debate_orchestrator.py"
    if bundled.is_file():
        return (
            bundled,
            bundled_dir / "cleanup_debate.py",
            PROJECT_ROOT,
            sys.executable,
            "PERSPECTIVE_ENGINE_DEBATE_BACKEND_URL",
        )
    mono_dir = autobbs_root() / ".agent" / "skills" / "debate_simulator" / "scripts"
    mono = mono_dir / "debate_simulator.py"
    if mono.is_file():
        return (
            mono,
            mono_dir / "cleanup_simulator.py",
            mono_dir.parent,
            _monorepo_python(),
            "DEBATE_BROADCAST_URL",
        )
    return None


@app.post("/api/monitor/debate/start")
async def debate_start():
    resolved = _resolve_debate_run()
    if resolved is None:
        raise HTTPException(
            status_code=503,
            detail="No debate script found (expected patterns/debate/scripts/debate_orchestrator.py).",
        )
    script_path, cleanup_script, cwd, runner_py, broadcast_env = resolved

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "debate_arena.log"
    log_f = await asyncio.to_thread(open, log_path, "a", encoding="utf-8")

    if cleanup_script.is_file():
        await asyncio.to_thread(
            subprocess.run,
            [runner_py, str(cleanup_script)],
            capture_output=True,
            cwd=str(cwd),
        )

    env = os.environ.copy()
    env[broadcast_env] = f"{pe_public_base()}/api/monitor/debate/broadcast"

    popen_kw: dict[str, Any] = {
        "cwd": str(cwd),
        "stdout": log_f,
        "stderr": subprocess.STDOUT,
        "env": env,
    }
    if sys.platform != "win32":
        popen_kw["start_new_session"] = True

    await asyncio.to_thread(
        subprocess.Popen, [runner_py, str(script_path)], **popen_kw
    )
    log_f.close()
    logger.info("Debate subprocess started; log=%s", log_path)
    return {"status": "success", "message": "Debate session started in background"}


# ── Feedback / Research Lab (AutoBBS-compatible paths) ───────────────────


@app.post("/api/monitor/feedback/broadcast")
async def feedback_broadcast(payload: dict):
    global feedback_state
    fb = payload.get("feedback_type", "")
    run_id = payload.get("run_id", "")

    if fb == "pipeline_start":
        feedback_state = {
            "status": "running",
            "run_id": run_id,
            "mode": payload.get("mode", "survey"),
            "count": payload.get("count", 0),
            "steps": [],
            "events": [],
        }
    elif fb == "step_complete":
        state = feedback_state or {}
        steps = state.get("steps", [])
        steps.append(
            {
                "step": payload.get("step"),
                "agent": payload.get("agent"),
                "artifact": payload.get("artifact"),
                "elapsed_ms": payload.get("elapsed_ms"),
            }
        )
        state["steps"] = steps
        feedback_state = state
    elif fb == "pipeline_complete":
        state = feedback_state or {}
        state["status"] = "complete"
        state["elapsed_ms"] = payload.get("elapsed_ms")
        feedback_state = state
    elif fb == "error":
        state = feedback_state or {}
        state["status"] = "error"
        state["error"] = payload.get("message", "Unknown error")
        feedback_state = state

    await ws_send("feedback_update", payload)
    return {"status": "ok"}


@app.get("/api/monitor/feedback/current")
async def feedback_current():
    if not feedback_state or feedback_state.get("status") == "idle":
        return {"status": "idle", "steps": [], "events": []}
    return feedback_state


@app.post("/api/monitor/feedback/reset")
async def feedback_reset():
    global feedback_state
    feedback_state = {"status": "idle", "steps": [], "events": []}
    return {"status": "idle"}


class ResearchStartRequest(BaseModel):
    feature_text: str
    count: int = Field(default=20, ge=1, le=500)
    mode: str = "survey"
    backend: str = "bedrock"
    agentic: bool = True
    dry_run: bool = False


# Accepted values for the feedback-simulator CLI (mirrors its argparse choices).
_ALLOWED_SIM_MODES = {"survey", "feedback"}
_ALLOWED_SIM_BACKENDS = {"gemini", "minimax", "litellm", "bedrock"}


def _is_bundled(path: Path) -> bool:
    """True when *path* lives inside this perspective-engine checkout."""
    return PROJECT_ROOT == path or PROJECT_ROOT in path.parents


def _feedback_sim_paths() -> tuple[Path, Path, Path, Path]:
    """(sim_dir, script, output_dir, feature_dir).

    Prefer the bundled patterns/customer_feedback scripts (standalone PE); fall
    back to the AutoBBS monorepo skill only when the bundle is absent.
    """
    bundled_dir = PROJECT_ROOT / "patterns" / "customer_feedback" / "scripts"
    bundled = bundled_dir / "feedback_simulator.py"
    if bundled.is_file():
        cf_root = PROJECT_ROOT / "patterns" / "customer_feedback"
        return bundled_dir, bundled, cf_root / "output", cf_root / "features"
    base = autobbs_root()
    sim_dir = base / ".agent" / "skills" / "customer_feedback_simulator" / "scripts"
    script = sim_dir / "feedback_simulator.py"
    output_dir = base / ".agent" / "skills" / "customer_feedback_simulator" / "output"
    feature_dir = (
        base / ".agent" / "skills" / "customer_feedback_simulator" / "features"
    )
    return sim_dir, script, output_dir, feature_dir


@app.post("/api/feedback-simulator/start")
async def research_start(req: ResearchStartRequest):
    sim_dir, script_path, output_dir, feature_dir = _feedback_sim_paths()

    if not script_path.is_file():
        raise HTTPException(
            status_code=503,
            detail=f"feedback_simulator.py not found at {script_path}. Set AUTOBBS_ROOT.",
        )

    feature_dir.mkdir(parents=True, exist_ok=True)
    feature_path = feature_dir / "feature_from_ui.md"
    feature_path.write_text(req.feature_text, encoding="utf-8")

    broadcast_url = os.environ.get(
        "FEEDBACK_BROADCAST_URL",
        f"{pe_public_base()}/api/monitor/feedback/broadcast",
    )

    # Constrain the user-controlled command arguments to known-good values
    # before they reach the subprocess (defence against argument injection).
    if req.mode not in _ALLOWED_SIM_MODES:
        raise HTTPException(status_code=400, detail=f"Invalid mode: {req.mode!r}")
    if req.backend not in _ALLOWED_SIM_BACKENDS:
        raise HTTPException(status_code=400, detail=f"Invalid backend: {req.backend!r}")

    runner_py = sys.executable if _is_bundled(script_path) else _monorepo_python()
    cmd = [
        runner_py,
        str(script_path),
        "--feature",
        str(feature_path),
        "--count",
        str(req.count),
        "--mode",
        req.mode,
        "--backend",
        req.backend,
        "--broadcast-url",
        broadcast_url,
    ]
    if req.agentic:
        cmd.append("--agentic")
    if req.dry_run:
        cmd.append("--dry-run")

    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "research_lab.log"
    ts = datetime.now(timezone.utc).isoformat()
    banner = f"\n{'=' * 72}\n[{ts}] Research Lab — subprocess\n  mode={req.mode} count={req.count}\n{'=' * 72}\n"

    log_f = await asyncio.to_thread(open, log_path, "a", encoding="utf-8")
    log_f.write(banner)
    log_f.flush()

    popen_kw: dict[str, Any] = {
        "cwd": str(sim_dir),
        "stdout": log_f,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform != "win32":
        popen_kw["start_new_session"] = True

    await asyncio.to_thread(subprocess.Popen, cmd, **popen_kw)
    log_f.close()

    return {
        "status": "started",
        "message": f"Research pipeline ({req.mode}, {req.count} respondents) launched.",
        "mode": req.mode,
        "count": req.count,
        "log_file": str(log_path),
    }


@app.get("/api/feedback-simulator/runs")
async def list_research_runs():
    _, _, output_dir, _ = _feedback_sim_paths()
    if not output_dir.is_dir():
        return []

    runs: list[dict] = []
    for d in sorted(output_dir.iterdir(), reverse=True):
        if not d.is_dir() or not d.name.startswith("run_"):
            continue
        meta_path = d / "pipeline_meta.json"
        meta = None
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        artifacts = [f.name for f in sorted(d.iterdir()) if f.is_file()]
        ts = d.name.replace("run_", "")
        runs.append(
            {
                "id": d.name,
                "timestamp": ts,
                "artifacts": artifacts,
                "count": meta.get("count", "?") if meta else "?",
                "mode": meta.get("type", "unknown") if meta else "unknown",
                "completed": (meta.get("completed") is not None) if meta else False,
            }
        )
    return runs


@app.get("/api/feedback-simulator/runs/{run_id}/artifact/{name}")
async def get_research_artifact(run_id: str, name: str):
    _, _, output_dir, _ = _feedback_sim_paths()
    safe_run = Path(run_id).name
    safe_name = Path(name).name
    artifact_path = output_dir / safe_run / safe_name
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")

    content = artifact_path.read_text(encoding="utf-8")
    if safe_name.endswith(".json"):
        try:
            return {"name": safe_name, "type": "json", "content": json.loads(content)}
        except json.JSONDecodeError:
            pass
    return {"name": safe_name, "type": "markdown", "content": content}


@app.delete("/api/feedback-simulator/runs/{run_id}")
async def delete_research_run(run_id: str):
    import shutil

    _, _, output_dir, _ = _feedback_sim_paths()
    safe_run = Path(run_id).name
    run_path = output_dir / safe_run
    if not run_path.is_dir():
        raise HTTPException(status_code=404, detail="Run not found")
    shutil.rmtree(run_path)
    return {"status": "deleted", "id": safe_run}


# ── Entry point ───────────────────────────────────────────────────────────


def main():
    port = int(os.environ.get("PE_SERVER_PORT", "8100"))
    # Bind to loopback by default; set PE_SERVER_HOST=0.0.0.0 to expose the
    # server on all interfaces when that is explicitly intended.
    host = os.environ.get("PE_SERVER_HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
