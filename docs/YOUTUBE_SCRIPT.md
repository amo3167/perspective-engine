# YouTube Demo Script

**Title**: "I Built AI Agents That Argue About Decisions — Then Another AI Reviews If They Lied"

**Duration**: 5 minutes

**Format**: Screen recording with voiceover

---

## 0:00–0:30 — Hook

*Show the final_review.md "Fabricated or Suspicious" section.*

"This is the output of a system I built. An independent AI reviewer just caught three other AI agents fabricating evidence during a meeting simulation. The strategic advisor invented a Microsoft Copilot statistic. The engineering director cited a Gartner study that doesn't exist. And the best part? The meeting was about whether to release the tool that runs these meetings."

---

## 0:30–1:30 — Demo Start

*Terminal: show the command.*

```bash
python -m engine.orchestrator \
    --topic "Should we open-source our internal AI meeting tool?" \
    --meeting-pack packs/should-we-open-source
```

"I define a meeting pack — a folder of JSON files that describes the agents, their personalities, the meeting structure, and the expected output format. Then I run it."

*Show agents spawning in terminal output.*

"Each agent is an independent process with its own LLM model and persona. The facilitator manages turn-taking. The agents can search the web and read reference documents."

---

## 1:30–2:30 — Meeting Phases

*Show terminal output as phases progress.*

"Phase 1: The innovation advocate writes the proposal. Phase 2: seven other agents debate it — a facilitator, a skeptic, a security reviewer, a product owner, a strategic advisor, a community lead, and an engineering director."

*Point to a discussion turn.*

"The facilitator detects when the conversation is going in circles and redirects. The skeptic pushes back. The strategic advisor forces the group to plan for success, not just failure."

"Phase 3: The author rewrites the proposal incorporating all feedback. Phase 4: The director makes the call — RELEASE, CONDITIONAL, or HOLD."

---

## 2:30–3:30 — The Final Review

*Show final_review.md output.*

"Phase 5 is where it gets interesting. A separate, more powerful AI model reads the entire transcript — it didn't participate in the meeting — and evaluates everything."

*Scroll through sections.*

"It measures process quality with actual numbers: who spoke how many times, who dominated, who was underutilized."

*Show evidence quality section.*

"It flags fabricated evidence. This strategic advisor cited Microsoft's Copilot rollout with specific details that don't exist in any public source. The reviewer caught it."

*Show meta-observations.*

"And it notices recursive irony: the meeting about releasing a meeting tool exhibited the exact circular argument flaw the tool is known for."

---

## 3:30–4:30 — Meeting Packs

*Show the packs/ directory structure.*

"The entire meeting is defined in 4 JSON files. Profiles define the agents — their personality, model, and tools. Prompts define their system instructions. Schemas define the structured output format. The template defines the phases."

*Open profiles.json briefly.*

"Want to simulate a hiring panel instead? Copy the folder, change the agents, run it. No code changes."

*Show the two included packs.*

"I've included two example packs: a strategic decision meeting and a technical architecture review."

---

## 4:30–5:00 — Close

"The tool uses LiteLLM, so it works with Gemini — which has a free tier — OpenAI, Anthropic, Ollama for local models, or any of 100+ other providers."

"The most interesting thing isn't the AI. It's what you learn about decision-making by watching AI agents argue poorly and then having a different AI explain exactly how they argued poorly."

"Link in the description. MIT license. The easiest contribution is creating a new meeting pack for a decision type you care about."

*Show GitHub URL.*

---

## Recording Notes

- Use a clean terminal with large font (14pt+)
- Dark theme for contrast
- Pre-run the meeting once so you know the timing
- Record the actual meeting running, not a simulation of a simulation
- Keep the voiceover conversational, not scripted-sounding
- End screen: GitHub URL + "Star if you found this interesting"
