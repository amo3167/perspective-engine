# LLM Provider Setup

Perspective Engine uses [LiteLLM](https://github.com/BerriAI/litellm) for LLM routing, which supports 100+ providers through a unified API.

## Configuring Models

Models are configured in your meeting pack's `profiles.json` under `litellm.model_map`:

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

Each agent in `profiles.json` references an alias (e.g., `"model": "fast-agent"`), which gets resolved to the concrete model string at runtime.

## Provider Setup

### Google Gemini (Recommended — Free Tier)

The easiest way to get started. Gemini Flash has a generous free tier.

1. Get an API key: https://aistudio.google.com/apikey
2. Set the environment variable:

```bash
export GEMINI_API_KEY=your-key-here
# or add to .env file
```

3. Use model strings like:

```json
"smart-agent": "gemini/gemini-2.5-pro-preview-03-25",
"fast-agent": "gemini/gemini-2.5-flash-preview-04-17"
```

### OpenAI

```bash
export OPENAI_API_KEY=your-key-here
```

```json
"smart-agent": "openai/gpt-4o",
"fast-agent": "openai/gpt-4o-mini",
"reasoning-agent": "openai/o1-mini"
```

### Anthropic

```bash
export ANTHROPIC_API_KEY=your-key-here
```

```json
"smart-agent": "anthropic/claude-sonnet-4-20250514",
"fast-agent": "anthropic/claude-haiku-3-5-20241022"
```

### Ollama (Local — Free)

Run models locally with [Ollama](https://ollama.ai). No API key needed.

```bash
# Install and start Ollama
ollama serve

# Pull a model
ollama pull llama3.1:8b
```

```json
"smart-agent": "ollama/llama3.1:70b",
"fast-agent": "ollama/llama3.1:8b"
```

Note: Local models may produce lower quality structured output. Gemini Flash is recommended for best results at no cost.

### AWS Bedrock

Configure AWS credentials in `~/.aws/credentials` or via environment variables.

```json
"smart-agent": "bedrock/anthropic.claude-sonnet-4-20250514-v1:0",
"fast-agent": "bedrock/amazon.nova-pro-v1:0"
```

### Azure OpenAI

```bash
export AZURE_API_KEY=your-key
export AZURE_API_BASE=https://your-deployment.openai.azure.com/
export AZURE_API_VERSION=2024-02-01
```

```json
"smart-agent": "azure/gpt-4o",
"fast-agent": "azure/gpt-4o-mini"
```

## Mixing Providers

You can use different providers for different roles. For example, use a strong model for the decision maker and final reviewer, and a fast model for discussion agents:

```json
"model_map": {
  "smart-agent": "openai/gpt-4o",
  "fast-agent": "ollama/llama3.1:8b",
  "reasoning-agent": "anthropic/claude-sonnet-4-20250514"
}
```

## Model Recommendations

| Role | Recommended Tier | Why |
|---|---|---|
| Final Reviewer (Phase 5) | `smart-agent` | Needs strong analytical ability for evidence flagging |
| Decision Maker | `smart-agent` | Nuanced judgment call |
| Facilitator | `fast-agent` | Structured decisions, less creative |
| Discussion Agents | `fast-agent` | Volume over depth per turn |
| Author | `fast-agent` or `reasoning-agent` | Needs good synthesis ability |

## Cost Optimization

A typical meeting with 8 agents and 20 discussion turns uses approximately:
- **Gemini Flash**: Free tier covers it
- **GPT-4o-mini**: ~$0.10-0.30 per meeting
- **GPT-4o**: ~$1-3 per meeting
- **Ollama**: Free (local compute only)

The Phase 5 final reviewer uses the most tokens (reads the entire transcript), so use your strongest model there and fast models elsewhere.
