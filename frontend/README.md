# Meeting Arena — Web UI

The Meeting Arena is a Vue 3 + Vuetify real-time viewer for watching meetings as they happen. It connects via WebSocket to the backend and displays:

- Phase progress tracker
- Live transcript with agent avatars
- Agent participant cards
- Final review rendering with evidence quality, meta-observations, and recommendations

## Status

The web UI is extracted from a larger monorepo and requires some adaptation for standalone use. The core meeting engine works fully via CLI without the web UI.

## Running Without the Web UI

The CLI experience is the primary interface:

```bash
python -m engine.orchestrator \
    --topic "Your topic here" \
    --meeting-pack packs/should-we-open-source

# Output files are written to output/:
# - meeting_transcript.json
# - meeting_notes.md
# - final_review.md
# - pipeline_meta.json
```

## Future

A standalone web UI is planned. Contributions welcome.
