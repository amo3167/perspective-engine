# What I Learned Building a Multi-Agent Meeting Simulator

*Source document for the engineering blog. Written as a first-person narrative about the journey from idea to working system, what surprised us, what failed, and where it's going.*

---

## The Question That Started It

What if you could stress-test a decision before the real meeting?

Not a pros-and-cons list. Not a ChatGPT prompt. An actual simulated meeting — with a facilitator managing turn-taking, a skeptic poking holes, a product owner pushing for shipping, an architect evaluating long-term impact — all arguing about your proposal before you present it to real humans.

That question became Perspective Engine: a multi-agent orchestration system where LLM-powered agents conduct structured meetings, debate proposals, reach decisions, and then get independently reviewed by a separate AI that checks whether anyone made up their evidence.

This post is the honest story of how it went from an idea to a working system — what we learned, what failed spectacularly, and why the failures turned out to be the most interesting part.

---

## From Idea to First Run

### The Spark

It started with a practical frustration. Architecture reviews take hours to coordinate. You gather six people, schedule a 90-minute slot, and half the concerns that get raised are predictable — things someone could have flagged asynchronously if they'd read the proposal carefully. The other half are genuinely surprising, and those are worth every minute.

What if you could get the predictable concerns surfaced *before* the real meeting, so the real meeting could focus on the surprising ones?

### The Architecture Decision

The first design choice was the most consequential: **each agent runs as an independent process with its own LLM and persona.** Not a single prompt with multiple voices. Not a chain-of-thought with role labels. Separate FastAPI servers, each on its own port, communicating via HTTP.

This felt over-engineered at first. But it meant:
- Each agent could use a different model (a fast model for discussion agents, a stronger model for the decision-maker)
- Agents could be swapped, added, or removed without touching code
- The system could theoretically distribute across machines
- Each agent maintained its own context window, preventing one dominant voice from consuming all the tokens

The orchestrator drives a 5-phase meeting flow:

1. **Proposal** — The author agent writes the initial document
2. **Discussion** — Agents debate, with a facilitator managing turn-taking and convergence detection
3. **Synthesis** — The author rewrites the proposal incorporating feedback
4. **Governance** — A decision-maker issues APPROVED, CONDITIONAL, or REJECTED
5. **Final Review** — A separate, more powerful model reads the entire transcript and independently evaluates everything

### The Meeting Pack Format

The second key decision was **externalizing the entire meeting configuration into portable "meeting packs."** A pack is a folder of 4 JSON files:

- `profiles.json` — Agent definitions (personality, model, tools)
- `agent_prompts.json` — System prompts per agent
- `message_schemas.json` — Structured output formats
- `meeting_template.json` — Phase definitions and meeting flow

Want to simulate a hiring panel instead of an architecture review? Copy the folder, edit the JSON, run it. No code changes. This turned out to be the decision that made the system genuinely useful — when someone asks "could this work for X?" the answer is always "let's find out in 20 minutes."

---

## What Surprised Us

### Agents Surface Real Concerns

The first production run was a technical architecture review for a real proposal: separating Win/Place market types in a betting platform. Within minutes, agents raised concerns that would have taken a human panel significantly longer to coordinate:

- The SRE agent flagged blast radius without being prompted
- The backend tech lead identified performance risks under load
- The platform architect proposed phased rollout with feature flags

These weren't generic observations. They were specific to the proposal content. The system read reference documents, applied domain knowledge, and produced actionable feedback.

### The AI Reviewed Its Own Release Decision

We ran a meeting where the agents debated whether to release the meeting simulator itself. The final reviewer — an independent AI model that didn't participate in the meeting — produced this meta-observation:

> "The meeting's own dynamics were evidence against the decision. The innovation-advocate dominated the framing, and the group converged on a consensus that felt more like momentum than critical thinking."

A meeting simulation simulating a meeting about releasing itself, and exhibiting the exact flaws it's designed to detect. You can't script that kind of irony.

### Synthetic Customers Give Surprisingly Actionable Feedback

We extended the multi-agent pattern beyond meetings into customer feedback simulation. Define 5 customer archetypes (Power User, Casual User, Privacy Skeptic, Change Resistant, Early Adopter), add statistical noise to generate 20 unique personas, broadcast a feature announcement, and collect structured feedback.

The output wasn't generic sentiment. The synthetic Power User demanded WebSocket API support with sub-100ms latency. The Privacy Skeptic wanted audit logs and transparent calculations. The Change Resistant user asked for a "Classic Mode" that mimics spreadsheet views. A product owner agent then synthesized 20 responses into a go/no-go recommendation with segment-specific strategies.

The tool doesn't replace real customer research. It gives you a structured preview of the concerns you'll likely hear, before you've committed to a direction.

---

## What Failed Spectacularly

### Circular Arguments

Phase 2 — the open discussion — ran 42 turns in one session. The last 15+ turns repeated the same concerns with minor variations. The agents weren't adding new information; they were restating positions with slightly different words.

This is a known LLM behaviour, but experiencing it in a multi-agent context was illuminating. The system has convergence detection (keyword frequency analysis triggers a warning when themes repeat 4+ times in 8 turns), but the facilitator agent didn't always act on it.

**What we learned:** Convergence detection needs to be enforced by the orchestrator, not just suggested to the facilitator. The hard turn limit is the real safeguard; the soft convergence signal is aspirational.

### Synthesis Failure

Phase 3 asks the author to read the entire transcript and produce a revised proposal incorporating feedback. In one run, the author couldn't synthesize. It produced a document that listed the feedback points but didn't actually revise the proposal. The system continued gracefully (the decision-maker worked with what it had), but this exposed a genuine capability gap.

**What we learned:** Synthesis — reading 20+ turns of multi-perspective debate and producing a coherent revised document — is one of the hardest tasks for current models. It requires holding contradictory viewpoints simultaneously and making judgment calls about which feedback to incorporate. This is exactly the skill that makes human authors valuable.

### Fabricated Evidence

The final reviewer flagged agents inventing citations. An engineering director cited an arXiv paper that doesn't exist. A community lead quoted "GitHub's OSS guide" statistics that GitHub has never published. An advisor referenced "Microsoft's Copilot rollout" with specific numbers that can't be sourced.

**What we learned:** This is actually the system working as designed. The final review phase exists specifically to catch this. But the rate — roughly 8% of agent responses contained fabricated or unverifiable claims — was a sobering reminder that multi-agent systems don't solve the hallucination problem; they distribute it across more voices. The independent reviewer is not optional.

### Negativity Spiral

When most of your agents are configured around risk assessment (skeptic, security reviewer, people & culture lead), the group converges on increasingly extreme safeguards. One run produced a consensus that required "executive compensation restructuring" as a precondition for showing a demo to three engineers. The governance became disproportionate to the action.

**What we learned:** Agent persona design is meeting design. If you build a panel of risk assessors, you get a risk-averse outcome. We added a Strategic Advisor agent whose explicit role is to name the opportunity cost every time someone raises a risk, and a Product Owner who gravitates toward "how do we ship this?" rather than "how do we prevent harm?" Balance in the panel produces balance in the output.

---

## The Evolution: How the System Improved Itself

### Iteration 1: Raw Debate

The first version was a simple round-robin discussion. Every agent spoke in order. The output was long, repetitive, and hard to extract value from.

### Iteration 2: Facilitated Discussion

Adding a facilitator agent that controls turn-taking transformed the quality. The facilitator nominates speakers, detects when someone has been silent too long, and signals when the discussion is converging. This mirrors real meeting dynamics — the best meetings have good facilitation, not just good participants.

### Iteration 3: Independent Review

The Phase 5 final review was the breakthrough. Having a separate model — one that didn't participate in the meeting — read the entire transcript and evaluate process quality, evidence credibility, and blind spots produced consistently the most valuable output. The reviewer catches things the participants can't see because they're inside the discussion.

### Iteration 4: Meeting Packs

Externalizing configuration into portable packs made the system genuinely reusable. We went from "one architecture review meeting hard-coded in Python" to "anyone can define a new meeting type in 20 minutes." This is when the use cases started multiplying — technical spikes, release strategy decisions, customer feedback, team retrospectives.

### Iteration 5: Multi-Model Routing

Using LiteLLM to route different agents to different models let us optimise cost and quality simultaneously. Discussion agents use fast, cheap models (they produce volume). The decision-maker and final reviewer use stronger models (they produce judgment). A typical meeting costs under $0.30 on Gemini Flash or runs entirely free on the free tier.

---

## What This Taught Us About Decision-Making

The most valuable output isn't the AI's decision. It's the structured process of surfacing concerns before the real meeting.

When you watch AI agents debate your proposal, you see:
- **Which concerns are predictable** — If the AI raises it, humans will too. Address it in advance.
- **Which perspectives are missing** — The final reviewer measures agent utilisation. If the security voice was underutilised, your meeting pack needs rebalancing. If the same happens in real meetings, maybe your real team has the same blind spot.
- **How framing shapes outcomes** — Change the agent personas and the same proposal gets a different reception. This makes the relationship between framing and outcome viscerally obvious.
- **Where your proposal is weakest** — The AI finds the seams. Not always the right seams, but enough to make you think harder before the real review.

The tool doesn't replace human judgment. It's a flight simulator for decisions — you practice with synthetic turbulence so the real flight goes better.

---

## Where It's Going

### Near-Term: Practical Use Cases

- **Proposal stress-testing** — Submit an RFC and let skeptical agents find the weak points before the real review panel
- **Conversation preparation** — Practice a difficult performance review or stakeholder conversation with 3 different persona configurations
- **Customer feedback preview** — Test product messaging with synthetic personas before committing to a campaign

### Medium-Term: Organisational Learning

- **Onboarding** — New hires experience simulated team dynamics. How do architecture reviews work here? What does the decision-maker care about?
- **Retrospective simulation** — Practice post-mortem facilitation with synthetic participants who replay actual incident dynamics

### The Bigger Question

Multi-agent simulation is not about replacing meetings. It's about a different question entirely: **what if you could practice your decisions before you made them?**

Athletes practice. Pilots practice. Surgeons practice. But organisational decision-making — the thing that consumes the most collective hours in any company — has no practice mode.

Until now, maybe.

---

## Try It Yourself

The system runs on any LiteLLM-supported provider — Gemini (free tier), OpenAI, Anthropic, Ollama (local), or AWS Bedrock. A meeting with 8 agents and 20 discussion turns takes about 15 minutes and costs under $0.30.

To create your own meeting:

1. Copy an existing meeting pack
2. Define your agents — give them distinct personalities and responsibilities
3. Add reference documents for domain context
4. Run the orchestrator with your topic
5. Read the final review first — it's consistently the most valuable output

The most interesting thing isn't the AI. It's what you learn about decision-making by watching AI agents argue poorly — and then having a different AI explain exactly how they argued poorly.

---

*Built with Python, FastAPI, LiteLLM, Redis, and an unreasonable number of late nights. The circular arguments are a feature, not a bug — they teach you what convergence failure looks like, which turns out to be useful when you notice it happening in real meetings too.*
