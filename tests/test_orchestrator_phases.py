"""orchestrator.py async phase handlers (run_phase_1/3/5) with mocked I/O."""

import asyncio

import engine.orchestrator as orch


def _run(coro):
    return asyncio.run(coro)


def _patch_turns(monkeypatch, responses):
    """Patch trigger_meeting_turn (queued responses) + notify_backend (recorder)."""
    calls = {"turn": [], "notify": []}
    resp_iter = iter(responses)

    async def fake_turn(*a, **k):
        calls["turn"].append(k)
        return next(resp_iter)

    async def fake_notify(payload):
        calls["notify"].append(payload)

    monkeypatch.setattr(orch, "trigger_meeting_turn", fake_turn)
    monkeypatch.setattr(orch, "notify_backend", fake_notify)
    return calls


def test_run_phase_1_happy_path(monkeypatch):
    calls = _patch_turns(
        monkeypatch,
        [
            {
                "status": "success",
                "message_type": "PROPOSAL_SUBMISSION",
                "content": {"x": 1},
            }
        ],
    )
    ok = _run(orch.run_phase_1(9000, "ns:ref", "m1", "topic"))
    assert ok is True
    kinds = [p["meeting_type"] for p in calls["notify"]]
    assert "meeting_turn" in kinds and "phase_complete" in kinds


def test_run_phase_1_retries_on_wrong_type_then_succeeds(monkeypatch):
    calls = _patch_turns(
        monkeypatch,
        [
            {"status": "success", "message_type": "WRONG"},
            {"status": "success", "message_type": "PROPOSAL_SUBMISSION", "content": {}},
        ],
    )
    assert _run(orch.run_phase_1(9000, "ns:ref", "m1", "topic")) is True
    assert len(calls["turn"]) == 2


def test_run_phase_1_returns_false_on_error(monkeypatch):
    _patch_turns(monkeypatch, [{"status": "error"}])
    assert _run(orch.run_phase_1(9000, "ns:ref", "m1", "topic")) is False


def test_run_phase_3_success_then_failure(monkeypatch):
    _patch_turns(
        monkeypatch,
        [{"status": "success", "message_type": "PROPOSAL_REVISION", "content": {}}],
    )
    assert _run(orch.run_phase_3(9000, "ns:ref", "m1")) is True

    _patch_turns(monkeypatch, [{"status": "error"}])
    assert _run(orch.run_phase_3(9000, "ns:ref", "m1")) is False


def _patch_phase5(monkeypatch, review_text=None, raise_exc=None, context=None):
    async def fake_get(self, ref):
        return context

    async def fake_notify(payload):
        pass

    monkeypatch.setattr(orch.SharedMemory, "get_context_ref", fake_get)
    monkeypatch.setattr(orch, "notify_backend", fake_notify)

    class _Msg:
        content = review_text

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    async def fake_acompletion(**kwargs):
        if raise_exc:
            raise raise_exc
        return _Resp()

    monkeypatch.setattr(orch.litellm, "acompletion", fake_acompletion)


def test_run_phase_5_parses_fenced_review(monkeypatch):
    _patch_phase5(
        monkeypatch,
        review_text='```json\n{"assessment": "solid"}\n```',
        context={"transcript": [{"a": 1}]},
    )
    out = _run(
        orch.run_phase_5(
            "ns:ref", "m1", {"architect_decision": "APPROVE"}, "test/model"
        )
    )
    assert out["assessment"] == "solid"
    assert out["message_type"] == "FINAL_REVIEW"


def test_run_phase_5_raw_fallback_when_unparseable(monkeypatch):
    _patch_phase5(monkeypatch, review_text="no json here at all", context=None)
    out = _run(orch.run_phase_5("ns:ref", "m1", {}, "test/model"))
    assert out["message_type"] == "FINAL_REVIEW"
    assert out["raw_review"] == "no json here at all"


def test_run_phase_5_handles_llm_exception(monkeypatch):
    _patch_phase5(monkeypatch, raise_exc=RuntimeError("api down"), context=None)
    out = _run(orch.run_phase_5("ns:ref", "m1", {}, "test/model"))
    assert out["error"] == "api down"
    assert out["message_type"] == "FINAL_REVIEW"


def test_run_phase_4_collects_decision_and_notes(monkeypatch):
    calls = _patch_turns(
        monkeypatch,
        [
            {
                "status": "success",
                "message_type": "ARCHITECT_APPROVAL",
                "content": {"decision": "APPROVED", "rationale": ["ok"]},
            },
            {
                "status": "success",
                "message_type": "MEETING_NOTES",
                "content": {"executive_summary": "done"},
            },
        ],
    )
    out = _run(orch.run_phase_4(9001, 9002, "ns:ref", "m1"))
    assert out["architect_decision"] == "APPROVED"
    assert out["meeting_notes"] == {"executive_summary": "done"}
    assert calls["notify"][-1]["architect_decision"] == "APPROVED"


def test_run_phase_4_defaults_unknown_when_architect_fails(monkeypatch):
    _patch_turns(
        monkeypatch,
        [
            {"status": "error"},
            {"status": "success", "message_type": "MEETING_NOTES", "content": {}},
        ],
    )
    out = _run(orch.run_phase_4(9001, 9002, "ns:ref", "m1"))
    assert out["architect_decision"] == "UNKNOWN"


def _patch_phase2(monkeypatch, fac_responses):
    """Patch the facilitator loop's I/O for run_phase_2."""
    notify = []
    resp_iter = iter(fac_responses)

    async def fake_fac(*a, **k):
        return next(resp_iter)

    async def fake_relevance(*a, **k):
        return {"decision": "ACCEPT"}

    async def fake_turn(*a, **k):
        return {"status": "success", "message_type": "COMMENT", "content": "hi"}

    async def fake_notify(payload):
        notify.append(payload)

    async def no_sleep(*a, **k):
        return None

    monkeypatch.setattr(orch, "trigger_facilitate", fake_fac)
    monkeypatch.setattr(orch, "trigger_relevance_check", fake_relevance)
    monkeypatch.setattr(orch, "trigger_meeting_turn", fake_turn)
    monkeypatch.setattr(orch, "notify_backend", fake_notify)
    monkeypatch.setattr(orch.asyncio, "sleep", no_sleep)
    return notify


def test_run_phase_2_ends_when_no_participants(monkeypatch):
    notify = _patch_phase2(monkeypatch, [{"decision": "END_DISCUSSION"}])
    _run(
        orch.run_phase_2(9000, {}, "ns:ref", "m1", time_limit=10, proposal_sections=[])
    )
    assert notify[-1]["meeting_type"] == "phase_complete"


def test_run_phase_2_nominate_triggers_accepted_agent(monkeypatch):
    notify = _patch_phase2(
        monkeypatch,
        [
            {"decision": "NOMINATE", "targets": ["r1"], "context": "go"},
            {"decision": "END_DISCUSSION"},
        ],
    )
    _run(
        orch.run_phase_2(
            9000, {"r1": 9001}, "ns:ref", "m1", time_limit=100, proposal_sections=[]
        )
    )
    kinds = [p["meeting_type"] for p in notify]
    assert "meeting_turn" in kinds  # the accepted agent spoke
    assert notify[-1]["meeting_type"] == "phase_complete"
