# Architecture

## Overview

Perspective Engine runs multi-agent meetings through a 5-phase orchestration pipeline. Each agent is an independent process with its own LLM model and persona.

## Components

### Orchestrator (`engine/orchestrator.py`)

The central coordinator that:

- Reads the meeting pack configuration
- Spawns agent node processes (one per agent)
- Drives the 5-phase meeting flow
- Makes the Phase 5 final review call directly (no agent node)
- Writes output files (transcript, notes, review)

### Agent Nodes (`engine/node.py`)

Each agent runs as an independent FastAPI server on its own port. Endpoints:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness check |
| `POST /meeting_turn` | Produce a structured meeting message |
| `POST /facilitate` | Facilitator only: decide who speaks next |
| `POST /relevance_check` | Evaluate a nomination and accept or pass |

The orchestrator communicates with agents via HTTP. This design means agents could run on different machines in the future.

### Shared Memory (`engine/shared_memory.py`)

Redis-backed key-value store that holds:

- Meeting transcript (append-only)
- Domain context (reference documents, handbook)
- Meeting metadata

Falls back to an in-memory dict when Redis isn't available. The in-memory fallback works because all agents share the same machine's address space via the orchestrator.

### Agent Tools (`engine/agent_tools.py`)

Agents can use tools during their LLM calls:

- **web_search**: DuckDuckGo search for real-time information
- **read_reference_file**: Read documents from the meeting pack's `reference/` directory

Tools are registered in a global registry and filtered per-agent based on their `skills` list in profiles.json.

## Meeting Flow

```
Phase 1: PROPOSAL
  Author agent writes the initial document.
  Orchestrator sends a directed prompt with the topic and schema.
  Output: PROPOSAL_SUBMISSION appended to transcript.

Phase 2: DISCUSSION (multi-turn)
  Facilitator decides who speaks next: OPEN_FLOOR, NOMINATE, PROMPT_SILENT.
  Nominated agents perform a RELEVANCE_CHECK and ACCEPT or PASS.
  Accepting agents produce COMMENT, AGREE, DISAGREE, or CHANGE_REQUEST.
  Orchestrator detects convergence and overrides premature END_DISCUSSION.
  Max turns and time limit enforced.

Phase 3: SYNTHESIS
  Author reads the full transcript and produces PROPOSAL_REVISION.
  Incorporates feedback, flags unresolved issues.

Phase 4: GOVERNANCE
  Decision maker reads transcript and issues ruling (APPROVED/CONDITIONAL/REJECTED).
  Facilitator produces MEETING_NOTES with summary, decisions, action items.

Phase 5: FINAL REVIEW
  Direct LLM call (no agent node) using the strongest available model.
  Reads full transcript + governance decision.
  Produces independent assessment: evidence quality, blind spots,
  meta-observations, quantitative agent utilization, recommendations.
```

## Convergence Detection

The facilitator detects repetition by analyzing keyword frequency in the last N turns. When the same themes repeat 4+ times in 8 turns, it generates a CONVERGENCE WARNING that encourages the facilitator to end the discussion.

The orchestrator also has hard overrides:
- Prevents END_DISCUSSION when agents haven't spoken yet
- Forces silent agents to speak after 4 consecutive rejection rounds
- Enforces a hard turn limit and time limit

## LLM Routing

All LLM calls go through [LiteLLM](https://github.com/BerriAI/litellm), which provides a unified API across 100+ providers. The meeting pack's `model_map` translates abstract aliases (`smart-agent`, `fast-agent`) to concrete model strings (`gemini/gemini-2.5-pro-preview-03-25`).

This means switching from Gemini to OpenAI to Ollama is a config change, not a code change.

## Output Files

| File | Format | Contents |
|---|---|---|
| `meeting_transcript.json` | JSON array | Every turn: agent, message type, content, timestamp |
| `meeting_notes.md` | Markdown | Executive summary, architect decision, rationale, conditions |
| `proposal_final.md` | Markdown | The final revised proposal document |
| `final_review.md` | Markdown | Independent review with all sections rendered |
| `pipeline_meta.json` | JSON | Meeting ID, timing, turn count, decision outcome |

## Shared Memory & Redis

### Key Layout

All keys use the prefix `meeting:mem` (set in `engine/shared_memory.py`). Full key format:

```
meeting:mem:{box_id}:{key}
```

Common keys:

| Key pattern | Writer | Description |
|---|---|---|
| `meeting:mem:shared:ref:{uuid}` | `store_context_ref` | Transcript + meeting state for a single run |
| `meeting:mem:shared:global_rules` | Debate orchestrator | Phase 2 tips / debate rules |
| `meeting:mem:shared:current_debate_session` | Debate orchestrator | Active debate marker |

### Multi-run / Parallel Meetings

Each meeting gets a unique `meeting_id` (UUID) embedded in the context-ref data, but the **Redis keys themselves** are not yet scoped by `meeting_id`. Two meetings running simultaneously will use separate `ref:{uuid}` keys (UUIDs are unique), so transcript data won't collide. However, singleton keys like `global_rules` are shared.

**Current safe usage:** one meeting at a time per Redis DB, or use separate `REDIS_DB` values via env for isolation.

### In-memory Fallback

When Redis is unavailable, `SharedMemory` stores everything in a process-local dict. This works for single-machine runs where the orchestrator and all agent nodes import the same module. It does **not** work if agents run as separate processes (the default) — each process gets its own dict. For multi-process runs, Redis is required.

### Patterns

The `patterns/debate/` and `patterns/customer_feedback/` directories reuse `engine/shared_memory.py` with the same `meeting:mem` prefix. Cleanup scripts scope their key deletion to pattern-specific prefixes (e.g. `meeting:mem:shared:ref:*` for debate) so they don't wipe unrelated meeting data.
