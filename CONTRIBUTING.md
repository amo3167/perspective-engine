# Contributing to Perspective Engine

The easiest and most valuable way to contribute is by **creating new meeting packs**. Each pack teaches the engine to facilitate a different kind of decision.

## Meeting Pack Contributions

1. Fork the repo
2. Create a new pack: `cp -r packs/technical-spike packs/your-pack-name`
3. Customize the agents, prompts, schemas, and template
4. Test it: `python -m engine.orchestrator --topic "Your topic" --meeting-pack packs/your-pack-name`
5. Include sample output in your PR so reviewers can see the quality
6. Submit a PR

### Pack Ideas

- **Hiring panel**: Simulate a hiring committee evaluating a candidate profile
- **Product launch**: Go/no-go decision with marketing, engineering, legal, finance perspectives
- **Incident retrospective**: Post-mortem facilitation with blameless analysis
- **Architecture decision record**: Multi-perspective trade-off analysis for design decisions
- **Budget allocation**: Competing teams make their case for resources
- **Risk assessment**: Red team / blue team security review

## Code Contributions

For engine changes:

1. Fork the repo
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make your changes
4. Test with at least one meeting pack
5. Submit a PR with a clear description

### Areas That Need Work

- **Standalone web UI**: The engine works via CLI but a self-contained web viewer would be great
- **In-memory fallback improvements**: The Redis fallback works but could be more robust
- **Testing**: Unit tests for the orchestrator phases and agent node endpoints
- **Pack validation**: A CLI tool to validate meeting pack JSON files before running

## Code Style

- Python 3.11+ with type hints
- Use `logging` for all output (not `print`)
- Keep functions focused and pure when possible

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(packs): add incident-retrospective meeting pack
fix(orchestrator): handle empty transcript in Phase 5
docs: add Ollama setup instructions to MODELS.md
```
