import sys
import os
import json
import asyncio
import httpx
import logging
import subprocess
import argparse
from datetime import datetime

PE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PE_ROOT not in sys.path:
    sys.path.insert(0, PE_ROOT)

from engine.shared_memory import SharedMemory
from engine.runtime import kill_processes_by_script_name

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("debate_orchestrator")

PROFILES_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "profiles.json")
)
NODE_SCRIPT = os.path.join(os.path.dirname(__file__), "debate_node.py")
AGENT_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "runs"))

TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
RUN_DIR = os.path.join(AGENT_BASE_DIR, f"run_{TIMESTAMP}")

DEBATE_BROADCAST_URL = os.environ.get(
    "PERSPECTIVE_ENGINE_DEBATE_BACKEND_URL", ""
).strip()


def _resolve_captain_agent(agents):
    """Return the team's captain agent, falling back to the first member.

    A team may list members without an explicit ``role == "captain"``; return
    the first agent in that case so downstream code never calls ``next()`` with
    no default and raises StopIteration.
    """
    return next(
        (p for p in agents if p.get("role") == "captain"),
        agents[0] if agents else None,
    )


async def notify_backend(payload: dict):
    if not DEBATE_BROADCAST_URL:
        return
    async with httpx.AsyncClient() as client:
        try:
            await client.post(DEBATE_BROADCAST_URL, json=payload, timeout=2.0)
        except Exception as e:
            logger.debug(f"Notification to backend failed: {e}")


def kill_old_nodes():
    import time

    killed = kill_processes_by_script_name(["debate_node.py"])
    if killed:
        logger.info(
            f"Cleaned up {killed} stale debate node(s). Waiting for ports to free..."
        )
        time.sleep(2)


async def start_nodes(profiles: list, model_map: dict[str, str]):
    processes = []
    os.makedirs(RUN_DIR, exist_ok=True)

    for agent in profiles:
        agent_dir = os.path.join(RUN_DIR, agent["id"])
        os.makedirs(agent_dir, exist_ok=True)

        alias = agent.get("model", "fast-agent")
        agent_model = model_map.get(alias, alias)
        logger.info(
            f"Starting Node for {agent['id']} on port {agent['port']} (model={agent_model})..."
        )

        cmd = [
            sys.executable,
            NODE_SCRIPT,
            "--port",
            str(agent["port"]),
            "--agent_id",
            agent["id"],
            "--soul",
            agent["soul"],
            "--skills",
            ",".join(agent["skills"]),
            "--model",
            agent_model,
            "--output_dir",
            agent_dir,
        ]

        # Start background process with parent environment
        # Redirect stderr to agent-specific log file (stdout is handled by the node's logging)
        log_path = os.path.join(agent_dir, f"{agent['id']}_stderr.log")
        log_file = open(log_path, "a", encoding="utf-8")
        env = os.environ.copy()
        proc = subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=log_file, env=env
        )
        processes.append({"id": agent["id"], "port": agent["port"], "proc": proc})

    logger.info("Nodes starting. Waiting for health checks...")
    await asyncio.sleep(5)

    async with httpx.AsyncClient() as client:
        for app in processes:
            try:
                resp = await client.get(
                    f"http://127.0.0.1:{app['port']}/health", timeout=2.0
                )
                if resp.status_code == 200:
                    logger.info(f"✅ Agent {app['id']} is healthy.")
                else:
                    logger.warning(f"⚠️ Agent {app['id']} returned {resp.status_code}")
            except Exception as e:
                logger.error(f"❌ Agent {app['id']} failed health check: {e}")

    return processes


async def trigger_node(
    port: int,
    context_ref: str,
    round_num: int,
    turn_index: int,
    insight_only=False,
    captain_insights=None,
):
    """Hits a single node and waits for completion."""
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post(
                f"http://127.0.0.1:{port}/debate_turn",
                json={
                    "context_ref": context_ref,
                    "round": round_num,
                    "turn_index": turn_index,
                    "next_urls": [],  # Disable automatic chaining
                    "insight_only": insight_only,
                    "captain_insights": captain_insights or [],
                },
            )
            if resp.status_code == 200:
                return resp.json().get("content", "")
        except Exception as e:
            logger.error(f"Failed to trigger node on port {port}: {e}")
        return ""


async def initialize_debate(topic: str) -> str:
    """Sets up the Redis state and broadcasts the debate start."""
    logger.info(f"🚀 INITIALIZING DEBATE: {topic}")

    debate_data = {
        "topic": topic,
        "round": 1,
        "transcript": [
            {
                "role": "system",
                "content": f"The debate has officially started on the subject of: {topic}",
            }
        ],
    }

    mem = SharedMemory()
    shared_key = await mem.store_context_ref(debate_data)

    # WebSocket Broadcast: Start
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    time_limit = config.get("rules", {}).get("time_limit_seconds", 420)

    await notify_backend(
        {
            "debate_type": "debate_start",
            "topic": topic,
            "context_ref": shared_key,
            "time_limit_seconds": time_limit,
            "timestamp": datetime.now().isoformat(),
        }
    )

    return shared_key


async def run_debate(context_ref: str, profiles: list):
    """Orchestrates Phase 1 (Sequential) and Phase 2 (Team Synthesis)."""

    pro_agents = [p for p in profiles if p.get("team") == "PRO"]
    con_agents = [p for p in profiles if p.get("team") == "CON"]

    pro_ports = [p["port"] for p in pro_agents]
    con_ports = [p["port"] for p in con_agents]

    # Resolve the captain *agent* once (falling back to the first team member),
    # so both the port and the id below come from the same source and a team
    # with no explicit captain role doesn't raise StopIteration later.
    # Resolve the captain *agent* once (falling back to the first team member),
    # so both the port and the id below come from the same source and a team
    # with no explicit captain role doesn't raise StopIteration later.
    pro_captain_agent = _resolve_captain_agent(pro_agents)
    con_captain_agent = _resolve_captain_agent(con_agents)
    pro_captain = pro_captain_agent["port"] if pro_captain_agent else None
    con_captain = con_captain_agent["port"] if con_captain_agent else None

    judge_agent = next((p for p in profiles if p.get("team") == "JUDGE"), None)
    judge_port = judge_agent["port"] if judge_agent else 9007

    # Phase 1: Constructive (1 agent at a time)
    logger.info("--- PHASE 1: CONSTRUCTIVE OPENING ---")

    # Interleave PRO and CON turns
    chain = []
    for i in range(max(len(pro_ports), len(con_ports))):
        if i < len(pro_ports):
            chain.append(pro_ports[i])
        if i < len(con_ports):
            chain.append(con_ports[i])

    turn_index = 0

    for port in chain:
        logger.info(f"Triggering Phase 1 turn for port {port}...")
        await trigger_node(port, context_ref, round_num=1, turn_index=turn_index)
        turn_index += 1
        await asyncio.sleep(2)  # Audience digest time

    # Phase 2: Free Debate (Team Captain Synthesis)
    logger.info("--- PHASE 2: TEAM SYNTHESIS (FREE DEBATE) ---")

    if pro_captain and pro_ports:
        # Team A (PRO) synthesis
        pro_member_ids = [p["id"] for p in pro_agents if p.get("role") != "captain"]
        pro_captain_id = pro_captain_agent["id"]
        logger.info(
            "Team PRO actively generating tactical insights behind closed doors..."
        )
        await notify_backend(
            {
                "debate_type": "debate_insight",
                "team": "PRO",
                "phase": "generating",
                "agents": pro_member_ids,
                "captain": pro_captain_id,
                "timestamp": datetime.now().isoformat(),
            }
        )
        insights_a = await asyncio.gather(
            *[trigger_node(p, context_ref, 2, 99, insight_only=True) for p in pro_ports]
        )
        valid_a = [i for i in insights_a if i and len(i) > 10]
        logger.info(
            f"Team PRO insights gathered ({len(valid_a)}). Forcing Captain (Port {pro_captain}) to synthesize..."
        )
        await notify_backend(
            {
                "debate_type": "debate_insight",
                "team": "PRO",
                "phase": "synthesizing",
                "agents": [pro_captain_id],
                "captain": pro_captain_id,
                "timestamp": datetime.now().isoformat(),
            }
        )
        await trigger_node(
            pro_captain, context_ref, 2, turn_index, captain_insights=valid_a
        )
        turn_index += 1
        await asyncio.sleep(2)

    if con_captain and con_ports:
        # Team B (CON) synthesis
        con_member_ids = [p["id"] for p in con_agents if p.get("role") != "captain"]
        con_captain_id = con_captain_agent["id"]
        logger.info(
            "Team CON actively generating tactical insights behind closed doors..."
        )
        await notify_backend(
            {
                "debate_type": "debate_insight",
                "team": "CON",
                "phase": "generating",
                "agents": con_member_ids,
                "captain": con_captain_id,
                "timestamp": datetime.now().isoformat(),
            }
        )
        insights_b = await asyncio.gather(
            *[trigger_node(p, context_ref, 2, 99, insight_only=True) for p in con_ports]
        )
        valid_b = [i for i in insights_b if i and len(i) > 10]
        logger.info(
            f"Team CON insights gathered ({len(valid_b)}). Forcing Captain (Port {con_captain}) to synthesize..."
        )
        await notify_backend(
            {
                "debate_type": "debate_insight",
                "team": "CON",
                "phase": "synthesizing",
                "agents": [con_captain_id],
                "captain": con_captain_id,
                "timestamp": datetime.now().isoformat(),
            }
        )
        await trigger_node(
            con_captain, context_ref, 2, turn_index, captain_insights=valid_b
        )
        turn_index += 1
        await asyncio.sleep(2)

    # Phase 3: Final Verdict
    logger.info("--- PHASE 3: FINAL VERDICT ---")
    if judge_port:
        logger.info(f"Summoning Judge (Port {judge_port}) to weigh the evidence...")
        await trigger_node(judge_port, context_ref, 3, turn_index)

    logger.info("Debate workflow complete.")


async def monitor_debate(context_ref: str):
    """Watches Redis and prints the transcript as it updates."""
    mem = SharedMemory()
    last_count = 0
    logger.info("Monitoring debate UI progress in console...")

    while True:
        data = await mem.get_context_ref(context_ref)
        if data:
            transcript = data.get("transcript", [])
            if len(transcript) > last_count:
                for msg in transcript[last_count:]:
                    name = msg.get("name", "System")
                    content = msg.get("content", "No content")
                    print(f"\n[{name}] {content}")
                last_count = len(transcript)

            if any(msg.get("name") == "J_Justice" for msg in transcript):
                break

        await asyncio.sleep(2)


async def main():
    parser = argparse.ArgumentParser(
        description="Multi-agent structured debate (PRO / CON / Judge)"
    )
    parser.add_argument(
        "--topic",
        type=str,
        default="Should jurisdictions support and regulate prediction markets? Argue from policy, ethics, and market-design perspectives.",
        help="Debate resolution / question",
    )
    args = parser.parse_args()

    if not os.path.exists(PROFILES_PATH):
        return
    with open(PROFILES_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)

    profiles = config.get("agents", [])
    rules = config.get("rules", {})
    time_limit = rules.get("time_limit_seconds", 420)
    litellm_cfg = config.get("litellm") or config.get("bedrock", {})
    model_map = litellm_cfg.get("model_map", {})

    kill_old_nodes()

    await start_nodes(profiles, model_map)

    # Store rules in Redis for nodes to access
    mem = SharedMemory()
    await mem.set("shared", "global_rules", rules)

    ref = await initialize_debate(args.topic)
    if ref is None:
        logger.error("❌ Debate failed to start.")
        return

    try:
        # Run debate flow and monitor concurrently
        debate_task = asyncio.create_task(run_debate(ref, profiles))
        monitor_task = asyncio.create_task(monitor_debate(ref))

        # Wait for the orchestrator to finish
        await asyncio.wait_for(debate_task, timeout=float(time_limit))

        # Give monitor a moment to print the final verdict cleanly
        await asyncio.sleep(3)
        monitor_task.cancel()

    except asyncio.TimeoutError:
        logger.warning(
            f"\n⏰ TIME LIMIT REACHED ({time_limit}s)! Forcing Emergency Verdict..."
        )
        judge_agent = next((p for p in profiles if p.get("team") == "JUDGE"), None)
        judge_port = judge_agent["port"] if judge_agent else 9007
        await trigger_node(judge_port, ref, 99, 99)
        if "monitor_task" in locals() and not monitor_task.done():
            monitor_task.cancel()

    print("\n--- Simulation Finished ---")
    print(f"Context ref: {ref} (Redis: meeting:mem:shared:…)")

    # WebSocket Broadcast: Finish
    await notify_backend(
        {
            "debate_type": "debate_finish",
            "context_ref": ref,
            "timestamp": datetime.now().isoformat(),
        }
    )

    print(
        "To terminate nodes: python patterns/debate/scripts/cleanup_debate.py (from perspective-engine root)"
    )


if __name__ == "__main__":
    asyncio.run(main())
