# Meeting Pack Format

A meeting pack is a self-contained folder that defines everything needed to run a multi-agent meeting. No code changes required — just create the JSON files and point the orchestrator at your pack.

## File Structure

```
my-pack/
  profiles.json          # Required: agent definitions and LLM config
  agent_prompts.json     # Required: system prompts per agent
  message_schemas.json   # Required: JSON schemas for structured messages
  meeting_template.json  # Required: phases, roles, and meeting flow
  reference/             # Optional: documents agents can read during the meeting
    context.md
    data.md
```

## profiles.json

Defines the agents and their LLM configuration.

```json
{
  "version": "3.0.0",
  "backend": "litellm",
  "litellm": {
    "default_model": "gemini/gemini-2.5-flash-preview-04-17",
    "model_map": {
      "smart-agent": "gemini/gemini-2.5-pro-preview-03-25",
      "fast-agent": "gemini/gemini-2.5-flash-preview-04-17"
    }
  },
  "rules": {
    "phase_2_time_limit_seconds": 300,
    "phase_2_general_tips": [
      "Maximum 3 bullet points per response.",
      "No agent can speak twice in a row."
    ]
  },
  "agents": [
    {
      "id": "facilitator",
      "short_name": "Facilitator",
      "team": "FACILITATOR",
      "role": "moderator",
      "port": 9920,
      "model": "fast-agent",
      "soul": "Neutral moderator who ensures balanced discussion.",
      "responsibilities": ["Manage discussion flow", "Compile meeting notes"],
      "skills": ["web_search", "read_reference_file"]
    }
  ]
}
```

### Agent Fields

| Field | Required | Description |
|---|---|---|
| `id` | Yes | Unique identifier used in templates and transcripts |
| `short_name` | No | Display name for UI |
| `team` | Yes | One of: `FACILITATOR`, `AUTHOR`, `REVIEWERS` |
| `role` | Yes | Semantic role: `moderator`, `author`, `reviewer`, `architect`, `decision_maker` |
| `port` | Yes | HTTP port for the agent's FastAPI server (must be unique) |
| `model` | No | Model alias from `model_map` (defaults to `smart-agent`) |
| `soul` | Yes | Character description that shapes the agent's personality |
| `responsibilities` | No | List of what this agent focuses on |
| `skills` | No | Tools the agent can use: `web_search`, `read_reference_file` |

### Model Map

The `model_map` translates abstract aliases to concrete LiteLLM model strings:

```json
"model_map": {
  "smart-agent": "openai/gpt-4o",
  "fast-agent": "openai/gpt-4o-mini",
  "reasoning-agent": "openai/o1-mini"
}
```

This lets you switch providers without editing agent definitions.

## agent_prompts.json

System prompts that define each agent's behavior, constraints, and response format.

```json
{
  "agents": {
    "facilitator": {
      "role": "Meeting Facilitator",
      "system_prompt": "You are the Meeting Facilitator...",
      "model_config": {
        "temperature": 0.3,
        "max_tokens": 2000
      }
    }
  }
}
```

### Template Variables

System prompts can use these variables (replaced at runtime):

- `${meeting_id}` — unique meeting identifier
- `${current_phase}` — current phase number (1-5)

## message_schemas.json

Defines the JSON structure agents must use for each message type. The engine injects these into prompts to guide LLM output.

Common message types:

| Type | Used In | Purpose |
|---|---|---|
| `COMMENT` | Phase 2 | General discussion point |
| `AGREE` | Phase 2 | Agreement with prior point |
| `DISAGREE` | Phase 2 | Disagreement with reasoning |
| `CHANGE_REQUEST` | Phase 2 | Specific change required |
| `PROPOSAL_SUBMISSION` | Phase 1 | Initial proposal |
| `PROPOSAL_REVISION` | Phase 3 | Revised proposal with feedback addressed |
| `ARCHITECT_APPROVAL` | Phase 4 | Decision: APPROVED/CONDITIONAL/REJECTED |
| `LEADERSHIP_DECISION` | Phase 4 | Decision: RELEASE/CONDITIONAL/HOLD |
| `MEETING_NOTES` | Phase 4 | Summary, decisions, action items |
| `FINAL_REVIEW` | Phase 5 | Independent review with evidence flagging |

## meeting_template.json

Defines the meeting flow: phases, roles, and what each phase does.

```json
{
  "template_name": "my_meeting",
  "description": "Description of the meeting type",

  "roles": {
    "facilitator": "facilitator-agent-id",
    "author": "author-agent-id",
    "decision_maker": "decider-agent-id",
    "reviewers": ["reviewer-1", "reviewer-2"]
  },

  "phases": [
    {
      "id": "proposal",
      "label": "Proposal",
      "phase_number": 1,
      "actor": "author",
      "expected_type": "PROPOSAL_SUBMISSION",
      "prompt": "Write the proposal for: ${topic}"
    },
    {
      "id": "discussion",
      "label": "Discussion",
      "phase_number": 2,
      "participants": ["reviewers", "decision_maker"],
      "max_turns": 20
    },
    {
      "id": "synthesis",
      "label": "Synthesis",
      "phase_number": 3,
      "actor": "author",
      "expected_type": "PROPOSAL_REVISION"
    },
    {
      "id": "decision",
      "label": "Decision",
      "phase_number": 4,
      "actor": "decision_maker",
      "expected_type": "LEADERSHIP_DECISION",
      "follow_up": {
        "actor": "facilitator",
        "expected_type": "MEETING_NOTES"
      }
    },
    {
      "id": "final_review",
      "label": "Final Review",
      "phase_number": 5,
      "model": "smart-agent",
      "expected_type": "FINAL_REVIEW"
    }
  ],

  "proposal_sections": ["section_1", "section_2"],

  "context": "reference/"
}
```

### Phase Prompt Variables

- `${topic}` — the meeting topic from the CLI
- `${proposal_sections_csv}` — comma-separated list of proposal sections

## Reference Documents

Place markdown files in the `reference/` directory. Agents with the `read_reference_file` skill can read these during the meeting. The orchestrator generates a handbook listing available files.

This is how you inject domain knowledge into the meeting without bloating prompts.

## Creating Your Own Pack

1. Copy an existing pack: `cp -r packs/technical-spike packs/my-decision`
2. Edit `profiles.json` — define your agents and their personalities
3. Edit `agent_prompts.json` — write system prompts for each agent
4. Edit `message_schemas.json` — define the JSON structure for each message type
5. Edit `meeting_template.json` — configure phases, roles, and flow
6. Add reference docs to `reference/` (optional)
7. Run: `python -m engine.orchestrator --topic "Your question" --meeting-pack packs/my-decision`
