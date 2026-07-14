"""orchestrator.py output + governance resolution — findings [6], [7], [8]."""

import asyncio
import os

import engine.orchestrator as orch
from engine.orchestrator import _resolve_architect_port


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
