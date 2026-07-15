"""orchestrator.py output + governance resolution — findings [6], [7], [8]."""

import asyncio
import os

import engine.orchestrator as orch
from engine.orchestrator import (
    _discover_proposal_key,
    _extract_nested_field,
    _render_item,
    _resolve_architect_port,
    _try_extract_proposal_doc,
)


def _run(coro):
    return asyncio.run(coro)


def test_resolve_architect_port_prefers_architect():
    port, aid = _resolve_architect_port(
        {"arch": 9000, "r1": 9001}, "arch", [{"id": "r1"}]
    )
    assert (port, aid) == (9000, "arch")


def test_resolve_architect_port_falls_back_to_reviewer():
    port, aid = _resolve_architect_port({"r1": 9001}, "", [{"id": "r1"}])
    assert (port, aid) == (9001, "r1")


def test_resolve_architect_port_zero_reviewers_returns_none():
    # Finding [8]: an empty reviewers list must not raise IndexError.
    assert _resolve_architect_port({"f": 9000}, "", []) == (None, None)


def test_resolve_architect_port_missing_from_port_map():
    assert _resolve_architect_port({}, "arch", [{"id": "r1"}]) == (None, None)


def test_write_outputs_tolerates_string_content_and_list_summary(tmp_path, monkeypatch):
    # Finding [6]: a facilitator transcript entry whose content is a string.
    # Finding [7]: a list-valued executive_summary.
    async def no_redis(self):
        return None

    monkeypatch.setattr(orch.SharedMemory, "_get_redis", no_redis)

    mem = orch.SharedMemory()
    ref = _run(
        mem.store_context_ref(
            {
                "transcript": [
                    {
                        "from_agent": "facilitator",
                        "message_type": "REFRAME",
                        "content": "let's reframe",
                    },
                ]
            }
        )
    )

    governance = {
        "meeting_notes": {"executive_summary": ["bullet one", "bullet two"]},
        "architect_decision": "APPROVE",
    }
    out_dir = str(tmp_path / "out")
    _run(orch.write_outputs(ref, out_dir, "m1", governance, start_time=0.0))

    notes = (tmp_path / "out" / "meeting_notes.md").read_text(encoding="utf-8")
    assert "bullet one" in notes
    assert os.path.isfile(os.path.join(out_dir, "meeting_transcript.json"))
    assert os.path.isfile(os.path.join(out_dir, "pipeline_meta.json"))


def test_write_outputs_empty_governance_writes_placeholder(tmp_path, monkeypatch):
    async def no_redis(self):
        return None

    monkeypatch.setattr(orch.SharedMemory, "_get_redis", no_redis)
    mem = orch.SharedMemory()
    ref = _run(mem.store_context_ref({"transcript": []}))

    out_dir = str(tmp_path / "out")
    _run(orch.write_outputs(ref, out_dir, "m2", {}, start_time=0.0))

    notes = (tmp_path / "out" / "meeting_notes.md").read_text(encoding="utf-8")
    assert "Meeting notes not available." in notes


def test_write_outputs_renders_proposal_rationale_and_conditions(tmp_path, monkeypatch):
    # Exercises the proposal_final.md path (dict/list/scalar sections) and the
    # architect rationale + conditions (dict and non-dict) rendering.
    async def no_redis(self):
        return None

    monkeypatch.setattr(orch.SharedMemory, "_get_redis", no_redis)

    mem = orch.SharedMemory()
    ref = _run(
        mem.store_context_ref(
            {
                "transcript": [
                    {
                        "message_type": "PROPOSAL_REVISION",
                        "content": {
                            "spike_document": {
                                "title": "Adopt X",
                                "problem_statement": "We need X.",
                                "proposed_solution": {
                                    "approach": "Do X carefully",
                                    "steps": ["step one", "step two"],
                                },
                                "impact_areas": ["latency", "cost"],
                            }
                        },
                    }
                ]
            }
        )
    )

    governance = {
        "meeting_notes": "Plain summary text.",
        "architect_decision": "APPROVE",
        "architect_content": {
            "rationale": ["clear win", "low risk"],
            "conditions": [
                {
                    "requirement": "Add tests",
                    "details": "cover new paths",
                    "owner": "team",
                    "due_date": "next week",
                },
                "Keep it simple",
            ],
        },
    }

    out_dir = str(tmp_path / "out")
    _run(orch.write_outputs(ref, out_dir, "m3", governance, start_time=0.0))

    proposal = (tmp_path / "out" / "proposal_final.md").read_text(encoding="utf-8")
    assert "# Adopt X" in proposal
    assert "## Problem Statement" in proposal
    assert "We need X." in proposal
    assert "### Approach" in proposal  # dict section, scalar sub-value
    assert "- step one" in proposal  # dict section, list sub-value
    assert "- latency" in proposal  # list section

    notes = (tmp_path / "out" / "meeting_notes.md").read_text(encoding="utf-8")
    assert "Plain summary text." in notes  # string summary
    assert "## Architect Rationale" in notes
    assert "- clear win" in notes
    assert "**Add tests**" in notes  # dict condition
    assert "- Keep it simple" in notes  # non-dict condition


def test_extract_nested_field_from_dict_and_list():
    assert _extract_nested_field({"a": {"summary": "S"}}, "summary") == "S"
    assert _extract_nested_field({"a": ['{"summary": "S"}']}, "summary") == "S"
    assert _extract_nested_field({"a": {"other": 1}}, "summary") == ""


def test_discover_proposal_key_picks_structured_key():
    schemas = {
        "PROPOSAL_REVISION": {
            "message_type": "PROPOSAL_REVISION",
            "my_doc": {"title": {}, "body": {}},
        }
    }
    assert _discover_proposal_key(schemas, "PROPOSAL_REVISION") == "my_doc"
    assert _discover_proposal_key({}, "PROPOSAL_REVISION") is None


def test_try_extract_proposal_doc_from_points_and_fallback():
    content = {"points": ['{"updated_spike_document": {"title": "T", "body": "B"}}']}
    assert _try_extract_proposal_doc(content) == {"title": "T", "body": "B"}
    absent = {"points": ["no json here"]}
    assert _try_extract_proposal_doc(absent) is absent


def test_render_item_variants():
    assert _render_item("plain") == "plain"
    out = _render_item({"description": "Do X", "agents": ["a1", "a2"]})
    assert "Do X" in out and "Agents: a1, a2" in out
    assert _render_item({}) == "{}"
    assert _render_item(5) == "5"
