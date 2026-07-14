#!/usr/bin/env bash
#
# Perspective Engine — Quickstart
#
# Run your first multi-agent meeting in under 2 minutes.
# Prerequisites: Python 3.11+, a Gemini API key (free tier works)
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== Perspective Engine — Quickstart ==="
echo ""

# Check Python version
if ! python3 -c "import sys; assert sys.version_info >= (3, 11)" 2>/dev/null; then
    echo "Error: Python 3.11+ is required."
    exit 1
fi

# Create venv if needed
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

echo "Installing dependencies..."
.venv/bin/pip install -q -r requirements.txt

# Check for API key
if [ -z "${GEMINI_API_KEY:-}" ]; then
    if [ -f .env ]; then
        export $(grep -v '^#' .env | xargs)
    fi
fi

if [ -z "${GEMINI_API_KEY:-}" ]; then
    echo ""
    echo "No GEMINI_API_KEY found. Get one free at: https://aistudio.google.com/apikey"
    echo "Then: export GEMINI_API_KEY=your-key-here"
    echo "Or:   echo 'GEMINI_API_KEY=your-key-here' > .env"
    exit 1
fi

echo ""
echo "Starting meeting: 'Should we adopt microservices?'"
echo "Using pack: packs/technical-spike"
echo "Agents will spawn, debate, and produce a final review."
echo ""

.venv/bin/python -m engine.orchestrator \
    --topic "Should we adopt microservices for our monolithic API?" \
    --meeting-pack packs/technical-spike

echo ""
echo "Done! Check the output/ directory for results:"
echo "  - meeting_transcript.json  (full conversation)"
echo "  - meeting_notes.md         (executive summary)"
echo "  - final_review.md          (independent AI review)"
echo "  - pipeline_meta.json       (timing and stats)"
