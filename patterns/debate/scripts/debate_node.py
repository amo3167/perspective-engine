import sys
import os
import uvicorn
import logging
import argparse
import httpx
import json
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel

import litellm

PE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if PE_ROOT not in sys.path:
    sys.path.insert(0, PE_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(PE_ROOT, ".env"))

from engine.shared_memory import SharedMemory
from engine.agent_tools import web_search as _web_search

litellm.drop_params = True
litellm.ssl_verify = False

DEFAULT_DEBATE_MODEL = os.getenv(
    "PERSPECTIVE_ENGINE_DEFAULT_MODEL",
    "gemini/gemini-2.5-flash-preview-04-17",
)

logger = logging.getLogger("debate_node")

app = FastAPI()
mem = SharedMemory()

agent_id = "unknown"
agent_soul = "generic soul"
agent_skills = []
agent_model = "gemini/gemini-2.5-flash-preview-04-17"
agent_output_dir = "agents/unknown"

DEBATE_BROADCAST_URL = os.environ.get("PERSPECTIVE_ENGINE_DEBATE_BACKEND_URL", "").strip()


async def notify_backend(payload: dict):
    if not DEBATE_BROADCAST_URL:
        return
    async with httpx.AsyncClient() as client:
        try:
            await client.post(DEBATE_BROADCAST_URL, json=payload, timeout=2.0)
        except Exception as e:
            logger.debug(f"Notification to backend failed: {e}")


def web_search(query: str, max_results: int = 4) -> str:
    return _web_search(query, max_results=max_results)


class DebateTurnRequest(BaseModel):
    context_ref: str
    round: int
    turn_index: int
    next_urls: Optional[List[str]] = []
    insight_only: Optional[bool] = False
    captain_insights: Optional[List[str]] = []


@app.get("/health")
async def health():
    return {"status": "online", "agent_id": agent_id, "model": agent_model}


@app.post("/debate_turn")
async def debate_turn(req: DebateTurnRequest):
    logger.info(f"Received turn for round {req.round}, turn {req.turn_index}")

    # 1. Fetch transcript from Redis
    debate_data = await mem.get_context_ref(req.context_ref)
    if not debate_data:
        logger.error(f"Could not find context ref: {req.context_ref}")
        return {"status": "error", "message": "context_ref_not_found"}

    transcript = debate_data.get("transcript", [])
    topic = debate_data.get("topic", "No topic")

    # 2. Optional: web search for grounding context
    search_context = ""
    try:
        search_result = web_search(f"{topic} latest news analysis 2026", max_results=3)
        if search_result and "error" not in search_result.lower():
            search_context = f"\n\n[Research Context from Web Search]:\n{search_result[:1500]}"
            logger.info(f"Web search returned {len(search_result)} chars of context.")
    except Exception as se:
        logger.warning(f"Web search skipped: {se}")

    rules = await mem.get("shared", "global_rules")
    tips = ""
    if rules and "general_tips" in rules:
        tips = f"\nGLOBAL RULES (Apply immediately):\n- " + "\n- ".join(rules["general_tips"])

    # 3. Build LLM prompt
    if req.insight_only:
        system_prompt = (
            f"You are '{agent_id}', a participant in a structured multi-agent debate.\n"
            f"Your persona: {agent_soul}\n"
            f"Your assigned skills: {', '.join(agent_skills) if agent_skills else 'General reasoning'}\n\n"
            f"DEBATE TOPIC: {topic}\n\n"
            f"DIRECTIONS: We are entering the Free Debate phase. Do NOT give a speech. "
            f"Provide a 1-2 sentence tactical insight identifying the biggest flaw in the opponent's arguments or a novel point your team MUST make. "
            f"This will be sent internally to your Team Captain. Be aggressive but analytical."
        )
    else:
        system_prompt = (
            f"You are '{agent_id}', a participant in a structured multi-agent debate.\n"
            f"Your persona: {agent_soul}\n"
            f"Your assigned skills: {', '.join(agent_skills) if agent_skills else 'General reasoning'}\n\n"
            f"DEBATE TOPIC: {topic}\n\n"
            f"RULES:\n"
            f"- Provide a concise, impacting argument or rebuttal (under 150 words).\n"
            f"- Reference and rebut specific points made by previous speakers.\n"
            f"- Stay in character. Do NOT break the fourth wall.\n"
            f"- Do NOT repeat the topic or preamble. Go straight to your argument.\n"
            f"- NEVER output 'Silence' or 'no thoughts produced'."
            f"{tips}"
            f"{search_context}"
        )

    messages = [{"role": "system", "content": system_prompt}]

    # Add previous debate turns as user messages
    for msg in transcript:
        if msg.get("role") == "system":
            continue
        name = msg.get("name", "Unknown")
        content = msg.get("content", "")
        if content and "Silence" not in content and len(content) > 10:
            messages.append({"role": "user", "content": f"[{name}]: {content}"})

    # Add a final user prompt to force engagement
    if any(msg.get("name") == "J_Justice" for msg in transcript) and agent_id == "J_Justice":
        logger.info("J_Justice already delivered a verdict. Ignoring emergency duplicate call.")
        return {"status": "success", "message": "already_done"}

    # Determine dynamic time limit for the prompt
    time_limit_secs = 300
    if rules and "time_limit_seconds" in rules:
        time_limit_secs = rules["time_limit_seconds"]
    time_limit_mins = int(time_limit_secs / 60)

    if req.captain_insights:
        insights_str = "\n".join([f"- {i}" for i in req.captain_insights])
        messages.append({"role": "user", "content": f"CAPTAIN BRIEFING: Your team members generated the following tactical insights behind closed doors:\n{insights_str}\n\nSynthesize these into a powerful, unified final answer for your team (under 150 words). Break their arguments apart."})
    elif len(messages) == 1:
        messages.append({"role": "user", "content": f"You are the first speaker. Open the debate on: {topic}"})
    elif agent_id == "J_Justice":
        messages.append({"role": "user", "content": "Deliver the final JUDGMENT and VERDICT based on the debate transcript above. Be balanced but firm."})
    else:
        messages.append({"role": "user", "content": f"It is now your turn. Respond to the previous arguments efficiently. The clock is ticking toward the {time_limit_mins}-minute limit."})
    

    # 4. Call LLM with retries
    # Judge needs more output room for full verdict; captain synthesis also benefits
    is_judge = agent_id.startswith("J_")
    is_captain_synth = bool(req.captain_insights)
    token_limit = 2048 if (is_judge or is_captain_synth) else 1024
    # Judge/captain verdicts should be substantial — retry if suspiciously short
    min_acceptable_chars = 300 if (is_judge or is_captain_synth) else 20

    logger.info(f"Calling LLM model='{agent_model}' for topic: {topic[:60]}... (max_tokens={token_limit})")
    content = None

    for attempt in range(3):
        try:
            resp = await litellm.acompletion(
                model=agent_model,
                messages=messages,
                max_tokens=token_limit,
                temperature=0.7,
            )
            raw = resp.choices[0].message.content
            finish_reason = getattr(resp.choices[0], "finish_reason", None) or "unknown"
            logger.info(f"Attempt {attempt+1}: finish_reason={finish_reason}, raw_len={len(str(raw))} chars.")
            if raw and len(str(raw).strip()) > 20:
                candidate = str(raw).strip()
                if len(candidate) < min_acceptable_chars and attempt < 2:
                    logger.warning(
                        f"Response too short for {agent_id} ({len(candidate)} < {min_acceptable_chars} chars). Retrying..."
                    )
                    await asyncio.sleep(2)
                    continue
                content = candidate
                logger.info(f"LLM success on attempt {attempt+1}: {len(content)} chars.")
                break
            logger.warning(f"Attempt {attempt+1}: empty/short response ({len(str(raw))} chars).")
        except Exception as e:
            logger.error(f"LLM error (attempt {attempt+1}): {str(e)}")
            await asyncio.sleep(3)

    if not content:
        content = f"[{agent_id} was unable to generate a response due to a temporary LLM connectivity issue.]"
        logger.error("All 3 LLM attempts failed. Using fallback content.")

    # 5. Write local history.md
    try:
        os.makedirs(agent_output_dir, exist_ok=True)
        history_path = os.path.join(agent_output_dir, "history.md")
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(history_path, "a", encoding="utf-8") as hf:
            if req.insight_only:
                hf.write(f"### Turn {req.turn_index} — TACTICAL INSIGHT ({timestamp})\n\n")
            elif req.captain_insights:
                hf.write(f"### Turn {req.turn_index} — CAPTAIN SYNTHESIS ({timestamp})\n\n")
            else:
                hf.write(f"### Turn {req.turn_index} — {timestamp}\n\n")
            hf.write(f"**Topic:** {topic}\n\n")
            hf.write(f"**Model:** `{agent_model}`\n\n")
            hf.write(f"**Response:**\n{content}\n\n---\n\n")
    except Exception as he:
        logger.error(f"Failed to write history: {he}")

    # 6. Handle Insight Only Mode
    if req.insight_only:
        logger.info(f"Insight generated ({len(content)} chars). Returning to coordinator silently.")
        return {"status": "success", "agent_id": agent_id, "content": content}

    # 7. Update transcript in Redis (Public Turns Only)
    latest_data = await mem.get_context_ref(req.context_ref)
    if not latest_data:
        latest_data = debate_data

    current_transcript = latest_data.get("transcript", [])
    
    # Prefix Team Synthesis if needed
    display_content = content
    if req.captain_insights:
        display_content = f"**[Team Synthesis]**\n{content}"
        
    current_transcript.append({"role": "assistant", "name": agent_id, "content": display_content})
    latest_data["transcript"] = current_transcript

    ref_parts = req.context_ref.split(":")
    await mem.set(ref_parts[0], ":".join(ref_parts[1:]), latest_data)

    logger.info(f"Response saved ({len(display_content)} chars). Passing baton...")

    # 8. WebSocket Broadcast: Turn
    asyncio.create_task(notify_backend({
        "debate_type": "debate_turn",
        "agent_id": agent_id,
        "content": display_content,
        "round": req.round,
        "turn_index": req.turn_index,
        "context_ref": req.context_ref,
        "timestamp": datetime.now().isoformat()
    }))

    # 6. Pass baton to next agent
    if req.next_urls:
        next_target = req.next_urls[0]
        remaining_chain = req.next_urls[1:]
        logger.info(f"Handing off to {next_target}")
        asyncio.create_task(pass_baton(next_target, req.context_ref, req.round, req.turn_index + 1, remaining_chain))
    else:
        logger.info("=== DEBATE CHAIN COMPLETED ===")

    return {"status": "success", "agent_id": agent_id, "content_length": len(content)}


async def pass_baton(url: str, ref: str, round_num: int, next_idx: int, remaining: List[str]):
    await asyncio.sleep(5)
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{url}/debate_turn",
                json={
                    "context_ref": ref,
                    "round": round_num,
                    "turn_index": next_idx,
                    "next_urls": remaining
                },
                timeout=120.0
            )
    except Exception as e:
        logger.error(f"Failed baton to {url}: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--agent_id", type=str, required=True)
    parser.add_argument("--soul", type=str, required=True)
    parser.add_argument("--skills", type=str, default="")
    parser.add_argument("--model", type=str, default="")
    parser.add_argument("--output_dir", type=str, default="")
    args = parser.parse_args()

    agent_id = args.agent_id
    agent_soul = args.soul
    agent_skills = args.skills.split(",") if args.skills else []
    agent_model = args.model if args.model else DEFAULT_DEBATE_MODEL
    agent_output_dir = args.output_dir if args.output_dir else os.path.join(
        PE_ROOT, "patterns", "debate", "runs", "adhoc", agent_id
    )

    # Configure file-based logging per agent
    os.makedirs(agent_output_dir, exist_ok=True)
    log_path = os.path.join(agent_output_dir, f"{agent_id}.log")

    # Root logger → file + console
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s - [{agent_id}] - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler()
        ]
    )
    logger = logging.getLogger("debate_node")
    logger.info(f"Starting {agent_id} | port={args.port} | model={agent_model} | soul={agent_soul[:60]}...")

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
