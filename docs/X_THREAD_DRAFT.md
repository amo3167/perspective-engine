# X/Twitter Thread Draft

**Hook strategy**: Lead with the evidence-flagging angle — it's the most surprising and shareable part.

---

**1/7 — Hook**

I built a tool where AI agents argue about decisions, then a separate AI reviews whether they made up their evidence.

Spoiler: they fabricate statistics constantly.

[Screenshot: final_review.md "Fabricated or Suspicious" section showing agents inventing Microsoft Copilot rollout statistics]

---

**2/7 — The evidence flagging**

The final reviewer caught the strategic-advisor citing "Microsoft's Copilot rollout to 300,000 employees succeeded because they led with 'watch it fail' moments."

No citation. No source. The AI just... made it up.

The reviewer flagged it with agent name and turn number.

[Screenshot: evidence_quality section with agent attribution]

---

**3/7 — The meta-observation**

The best part: I asked the agents to debate whether to release the meeting simulation tool.

The reviewer noticed: "The group's fear of over-governance led to... over-governance of a 2-3 person demo, proving the tool's point about human bias toward risk aversion."

A meeting simulation simulating a meeting about releasing itself. And exhibiting its own flaws.

---

**4/7 — The numbers**

The reviewer doesn't just give vibes. It counts:

- innovation-advocate: 5 turns (24%) — dominated
- strategic-advisor: 2 turns (10%) — underutilized despite having the strongest evidence
- strategy-facilitator: 1 turn (5%) — should have intervened more

Process quality measured in numbers, not feelings.

[Screenshot: agent_utilization stats]

---

**5/7 — How it works**

5 phases:
1. Author proposes
2. Agents debate (facilitator manages turn-taking)
3. Author synthesizes feedback
4. Decision maker rules
5. Independent AI reviews everything

The interesting part isn't the LLM calls — it's the portable "meeting pack" format. 4 JSON files define the entire meeting: agents, prompts, schemas, phases.

---

**6/7 — Create your own**

Want agents to simulate a hiring panel? Product launch go/no-go? Architecture review?

Copy a pack, edit the JSON, run it. No code changes.

The engine handles orchestration, turn-taking, convergence detection, and the independent final review.

---

**7/7 — Open source**

It's called Perspective Engine. MIT license. Works with Gemini (free), OpenAI, Ollama (local), or any LiteLLM-supported provider.

github.com/perspective-engine/perspective-engine

The most interesting thing isn't the AI — it's what you learn about decision-making by watching AI agents argue poorly.

---

## Posting Notes

- Post thread on a weekday morning (Tue-Thu, 9-11am local time for US audience)
- Include 2-3 screenshots: evidence flagging section, meta-observations, agent utilization stats
- Pin the first tweet
- Reply to the thread with: "The sample output is in examples/sample_output/ — you can read the full final review without installing anything."
