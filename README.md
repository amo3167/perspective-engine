# Perspective Engine

[![CI](https://github.com/amo3167/perspective-engine/actions/workflows/ci.yml/badge.svg)](https://github.com/amo3167/perspective-engine/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Multi-agent meeting simulation where AI personas debate your decisions — then a separate AI reviews whether they made up their evidence.**

<!-- TODO: Replace with actual demo GIF -->
<!-- ![Demo](docs/demo.gif) -->

---

## What It Does

You define a **meeting pack** — a portable JSON config with agents, phases, and schemas — and the engine runs a structured 5-phase meeting:

1. **Proposal** — An author agent writes the initial document
2. **Discussion** — A facilitator drives multi-turn debate between reviewer agents
3. **Synthesis** — The author incorporates feedback into a revised proposal
4. **Governance** — A decision maker issues APPROVED / CONDITIONAL / REJECTED
5. **Final Review** — An independent AI (the strongest model you have) reads the entire transcript and evaluates decision quality, catches fabricated evidence, and flags blind spots

Each agent has a distinct persona ("soul"), responsibilities, and access to tools (web search, reference documents). The facilitator manages turn-taking, detects circular arguments, and prevents negativity spirals.

## Why It's Interesting

- **Evidence flagging**: The final reviewer catches agents that invent statistics or cite non-existent studies. LLMs fabricate evidence constantly — the reviewer calls out every instance with agent attribution and turn numbers.
- **Meta-observations**: When the meeting topic is self-referential (e.g., "should we open-source the meeting tool?"), the reviewer detects recursive irony in the discussion dynamics.
- **Quantitative process analysis**: Turn counts per agent, dominance/utilization ratios, echo chamber detection — not vibes, numbers.
- **Portable meeting packs**: The entire meeting configuration is a folder of JSON files. Create your own pack for any decision: architecture reviews, hiring decisions, strategy debates, product launches.

## Quickstart

**Prerequisites:** Python 3.11+, a [Gemini API key](https://aistudio.google.com/apikey) (free tier works)

```bash
cd perspective-engine

# Set up
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Configure
echo "GEMINI_API_KEY=your-key-here" > .env

# Run
python -m engine.orchestrator \
    --topic "Should we adopt microservices for our monolithic API?" \
    --meeting-pack packs/technical-spike
```

Or use the quickstart script:

```bash
cd perspective-engine
export GEMINI_API_KEY=your-key-here
./examples/quickstart.sh
```

Output is written to `output/`:

| File | What It Contains |
|---|---|
| `meeting_transcript.json` | Full conversation with all agent turns |
| `meeting_notes.md` | Executive summary, decisions, action items |
| `final_review.md` | Independent review with evidence flagging |
| `pipeline_meta.json` | Timing, turn counts, decision outcome |

## Architecture

```
┌─────────────────────────────────────────────────┐
│                  Orchestrator                     │
│  Manages phases, spawns agents, broadcasts events │
└────────┬──────────┬──────────┬──────────┬────────┘
         │          │          │          │
    ┌────▼───┐ ┌────▼───┐ ┌────▼───┐ ┌────▼───┐
    │ Agent  │ │ Agent  │ │ Agent  │ │ Agent  │
    │ Node 1 │ │ Node 2 │ │ Node 3 │ │ Node N │
    │ :9920  │ │ :9921  │ │ :9922  │ │ :992N  │
    └────┬───┘ └────┬───┘ └────┬───┘ └────┬───┘
         │          │          │          │
    ┌────▼──────────▼──────────▼──────────▼────┐
    │          SharedMemory (Redis)              │
    │     Transcript + Context + State          │
    │     (falls back to in-memory dict)        │
    └───────────────────────────────────────────┘
```

Each agent runs as an independent FastAPI process with its own LLM model. The orchestrator communicates via HTTP. All agents share a transcript through Redis (or an in-memory fallback when Redis isn't available).

**LLM routing** is handled by [LiteLLM](https://github.com/BerriAI/litellm), so you can use any provider: Gemini, OpenAI, Anthropic, AWS Bedrock, Ollama (local), and 100+ others.

## Meeting Packs

A meeting pack is a folder with 4 JSON files:

```
packs/my-decision/
  profiles.json          # Agent definitions: id, soul, model, port, skills
  agent_prompts.json     # System prompts per agent
  message_schemas.json   # JSON schemas for each message type
  meeting_template.json  # Phases, roles, proposal sections
  reference/             # Optional: context documents agents can read
    context.md
```

See [docs/MEETING_PACK_FORMAT.md](docs/MEETING_PACK_FORMAT.md) for the full spec.

### Included Example Packs

| Pack | Topic | Agents |
|---|---|---|
| `should-we-open-source` | Strategic decision about releasing an internal tool | 8 agents: facilitator, advocate, director, community lead, security reviewer, skeptic, PO, strategic advisor |
| `technical-spike` | Architecture review with proposal and governance | 6 agents: facilitator, lead dev, architect, backend lead, frontend lead, SRE |

## LLM Provider Setup

Configure your provider in the meeting pack's `profiles.json` under `litellm.model_map`:

```json
{
  "litellm": {
    "model_map": {
      "smart-agent": "gemini/gemini-2.5-pro-preview-03-25",
      "fast-agent": "gemini/gemini-2.5-flash-preview-04-17",
      "reasoning-agent": "gemini/gemini-2.5-flash-preview-04-17"
    }
  }
}
```

**Gemini (free tier):** Set `GEMINI_API_KEY` — no cost for flash models.

**OpenAI:** Set `OPENAI_API_KEY` and use `openai/gpt-4o` or `openai/gpt-4o-mini`.

**Ollama (local):** Run `ollama serve` and use `ollama/llama3.1:8b` — completely free, runs on your machine.

**AWS Bedrock:** Configure `~/.aws/credentials` and use `bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0`.

See [docs/MODELS.md](docs/MODELS.md) for detailed provider setup.

## Redis (Optional)

Redis is used for shared memory between agents. If Redis isn't available, the engine falls back to an in-memory dict (works fine for single-machine use).

To run Redis:

```bash
docker run -d --name redis -p 6379:6379 redis:alpine
```

## Project Structure

```
perspective-engine/
  engine/
    orchestrator.py       # Meeting orchestrator (5 phases)
    node.py               # Agent node (FastAPI per-agent process)
    shared_memory.py      # Redis-backed shared state
    agent_tools.py        # Tool registry (web search, file reading)
  packs/
    should-we-open-source/ # Example: strategic decision pack
    technical-spike/       # Example: architecture review pack
  examples/
    quickstart.sh          # Run your first meeting
    sample_output/         # Pre-generated output to read
  docs/
    MEETING_PACK_FORMAT.md
    ARCHITECTURE.md
    MODELS.md
  frontend/               # Web UI (Vue 3 — coming soon)
```

## License

MIT — do whatever you want with it.

## Contributing

Meeting packs are the easiest way to contribute. Create a pack for a decision type you care about (hiring panels, product launches, incident retrospectives) and submit a PR.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
