"""Pattern-script fixes — findings [9], [11], [13]."""

import debate_orchestrator
import marketing_agent
import po_analyst
from aggregator import compute_stats, render_report


# ── Finding [9]: debate captain resolution ────────────────────────────────


def test_captain_resolution_prefers_explicit_captain():
    agents = [{"id": "a", "role": "member"}, {"id": "b", "role": "captain"}]
    assert debate_orchestrator._resolve_captain_agent(agents)["id"] == "b"


def test_captain_resolution_falls_back_to_first_member():
    # No agent has role == "captain" — must return the first, not raise.
    agents = [{"id": "a", "role": "member"}, {"id": "b", "role": "member"}]
    assert debate_orchestrator._resolve_captain_agent(agents)["id"] == "a"


def test_captain_resolution_empty_team():
    assert debate_orchestrator._resolve_captain_agent([]) is None


# ── Finding [13]: non-mutating _coalesce_consecutive_roles ─────────────────


def _coalesce_is_non_mutating(fn):
    original = [
        {"role": "user", "content": [{"text": "a"}]},
        {"role": "user", "content": [{"text": "b"}]},
    ]
    snapshot = [dict(role=m["role"], content=list(m["content"])) for m in original]

    first = fn(original)
    # Input untouched.
    assert [m["content"] for m in original] == [m["content"] for m in snapshot]
    # Adjacent same-role messages merged in the output.
    assert len(first) == 1
    assert first[0]["content"] == [{"text": "a"}, {"text": "b"}]

    # Calling again on the same input yields the same result (no drift/growth).
    second = fn(original)
    assert second[0]["content"] == first[0]["content"]


def test_marketing_agent_coalesce_non_mutating():
    _coalesce_is_non_mutating(marketing_agent._coalesce_consecutive_roles)


def test_po_analyst_coalesce_non_mutating():
    _coalesce_is_non_mutating(po_analyst._coalesce_consecutive_roles)


# ── Finding [11]: aggregator quote rendering ───────────────────────────────


def test_render_report_tolerates_quote_without_feedback():
    responses = [
        {"sentiment": 5, "would_use": True, "archetype_label": "Fan"},  # no 'feedback'
        {"sentiment": 1, "feedback": "hated it", "archetype_label": "Critic"},
    ]
    stats = compute_stats(responses)
    md = render_report(stats)  # must not raise KeyError on the feedback-less quote
    assert isinstance(md, str)
    assert "hated it" in md
