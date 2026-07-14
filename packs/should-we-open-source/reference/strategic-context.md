# Strategic Context: Open-Sourcing Perspective Engine

Reference document for all agents participating in the open-source decision meeting. Contains evidence from actual system runs, landscape analysis, and context for a balanced discussion about making this tool publicly available.

---

## 1. What We Built

### Perspective Engine
A configurable multi-agent orchestration system where LLM agents with distinct personas conduct structured meetings through phased orchestration. The system is provider-agnostic (AWS Bedrock, Gemini, OpenAI, Ollama via LiteLLM) and uses portable "meeting packs" — JSON configuration that defines agents, phases, schemas, and reference data.

### Key Components
- **Engine core**: Orchestrator, per-agent FastAPI processes, shared memory (Redis or in-memory)
- **Meeting packs**: Portable JSON configs that define agent personas, discussion rules, and output schemas
- **Three patterns**: Structured meetings (5-phase), debate (PRO/CON/Judge), customer feedback simulation
- **Frontend**: Vue.js real-time monitoring dashboard via WebSocket

### Evidence from Runs
- Agents surface real concerns within minutes that take human panels hours to coordinate
- Facilitator detects convergence and moves discussion forward autonomously
- Decision-maker issues structured conditional approvals with concrete conditions
- Total time from start to decision: under 15 minutes

### Known Limitations (observed, not theoretical)
- **Circular arguments**: Phase 2 can run 40+ turns repeating the same concerns
- **Synthesis failure**: Author agent sometimes cannot synthesize discussion into revised proposal
- **Negativity spiral**: Risk-focused agents converge on increasingly extreme safeguards
- **Hallucinated evidence**: Agents fabricate citations (arXiv papers, case studies) to support arguments
- **Model constraints**: LLMs occasionally produce malformed structured outputs

---

## 2. The Open-Source Landscape

### Similar Projects
The multi-agent simulation space is active and growing:
- **AutoGen (Microsoft)**: Multi-agent conversation framework — MIT licensed, 40k+ GitHub stars
- **CrewAI**: Role-based multi-agent orchestration — MIT licensed, 25k+ stars
- **LangGraph**: Graph-based agent workflows — MIT licensed, part of LangChain ecosystem
- **MetaGPT**: Multi-agent software development simulation — MIT licensed
- **ChatDev**: Communicative agents for software development — Apache 2.0

### What Makes Perspective Engine Different
- **Meeting-centric**: Purpose-built for structured decision-making, not general-purpose agent chat
- **Portable meeting packs**: Configuration-driven personas, phases, and schemas — not hardcoded
- **Provider-agnostic**: LiteLLM means any LLM backend (Bedrock, Gemini, OpenAI, Ollama local)
- **Built-in governance**: Phase-based flow with facilitator convergence detection and architect approval gates
- **Self-critical**: Phase 5 Final Review evaluates the meeting's own process quality, blind spots, and evidence fabrication

### Market Timing
- Multi-agent frameworks are a hot space in 2025–2026; early entrants capture mindshare
- Most existing tools focus on code generation or general chat — meeting simulation is underserved
- Companies are actively exploring how to use AI for decision support, not just productivity

---

## 3. Open-Source Benefits

### Developer Community and Adoption
- Public repo enables organic discovery — developers searching for multi-agent tools find Perspective Engine
- Meeting packs as a contribution model is unique — people can contribute personas and scenarios, not just code
- Open issues and PRs create a feedback loop that improves the tool faster than internal use alone

### Talent and Reputation
- OSS contributions signal engineering capability to the market
- Contributors become advocates; users become a hiring pipeline
- Conference talks and blog posts have a tangible artifact to reference

### Innovation Acceleration
- External contributors bring use cases we haven't imagined
- Academia can use it for research on multi-agent deliberation and AI governance
- Integration with other OSS tools (LangChain, LlamaIndex) expands the ecosystem

### Strategic Positioning
- Being the reference implementation for "AI-assisted decision meetings" is a defensible position
- Open-source builds trust that proprietary tools cannot — users can inspect every prompt and persona
- First-mover advantage in meeting-focused multi-agent orchestration

---

## 4. Open-Source Risks

### Intellectual Property
- The codebase may contain patterns, prompts, or architectural decisions that represent competitive advantage
- Meeting pack templates could reveal internal decision-making processes or organizational culture
- Agent prompts encode domain expertise that took significant effort to develop

### Security Exposure
- Public code invites security scrutiny — any vulnerabilities become visible to attackers
- Configuration files, environment variable patterns, and infrastructure assumptions become public
- Dependencies must be audited for known CVEs before release
- Any accidentally committed secrets (API keys, internal URLs) in git history are permanently exposed

### Maintenance Burden
- Open-source creates an implicit social contract — users expect issues to be triaged, PRs reviewed, releases maintained
- A repo with no activity after initial release signals abandonment and damages reputation
- Community management requires ongoing time: CoC enforcement, issue triage, contributor onboarding
- Risk of scope creep from community feature requests

### Quality and Reputation
- Known limitations (circular arguments, hallucinated evidence) become publicly visible
- Code quality standards for OSS are higher than internal tools — documentation, tests, CI must be solid
- Negative reviews or critical blog posts are permanent and public
- If the tool is not production-grade, releasing it could be seen as dumping unfinished work

### Legal and Licensing
- License choice has long-term implications (MIT vs Apache 2.0 vs AGPL)
- Must verify all dependencies are license-compatible
- Contributor License Agreement (CLA) may be needed to protect IP
- Company legal team may need to review before public release

---

## 5. Licensing Options

| License | Permissiveness | Key Implication |
| :--- | :--- | :--- |
| **MIT** | Maximum | Anyone can use, modify, sell. No patent protection. Simple. |
| **Apache 2.0** | High | Like MIT but includes patent grant. Protects contributors. |
| **AGPL-3.0** | Copyleft | Modifications must be shared. Deters proprietary forks. |
| **BSL (Business Source License)** | Time-delayed | Source-available now, becomes open after delay. Used by HashiCorp, MariaDB. |

Most multi-agent frameworks use MIT or Apache 2.0. AGPL would limit corporate adoption. BSL is controversial in the OSS community.

---

## 6. What a Good Open-Source Release Looks Like

### Minimum Viable Release
- Clean README with clear "what this is / what this isn't" positioning
- One working meeting pack as a complete example
- Installation guide (pip install, env setup, first meeting in 5 minutes)
- LICENSE file (MIT or Apache 2.0)
- CONTRIBUTING.md with clear guidelines for meeting pack contributions
- CI pipeline (linting, pack validation, basic smoke tests)
- No internal references, no company-specific context in the public repo

### What to Strip Before Release
- All internal meeting packs and reference documents
- Company-specific agent prompts and personas
- Git history containing any sensitive data
- Internal infrastructure references (Redis endpoints, Bedrock regions, etc.)
- Any `.env` files or credentials

### Community Building
- "Good first issue" labels for newcomers
- Meeting pack contribution template
- Discussion forum or Discord for users
- Monthly release cadence to signal active maintenance

---

## 7. What Success Looks Like

### 30-Day Success
- 50+ GitHub stars from organic discovery
- 2-3 external contributors submit meeting pack PRs
- First blog post or tweet from an external user

### 90-Day Success
- 500+ stars, active issue tracker
- Featured in a multi-agent framework comparison article
- Used by at least one university research group
- 5+ community-contributed meeting packs

### 12-Month Success
- 2000+ stars, recognized as the reference tool for AI-assisted decision meetings
- Conference talk accepted (PyCon, AI Engineer Summit, etc.)
- Integration with at least one major LLM framework
- Active contributor community with 10+ regular contributors

### What Failure Looks Like
- Repo with <10 stars after 90 days — no organic interest
- Zero external contributions — the tool doesn't solve a real problem
- Negative coverage — "company dumps unfinished AI tool on GitHub"
- Maintenance abandoned — last commit 6 months ago, issues piling up
