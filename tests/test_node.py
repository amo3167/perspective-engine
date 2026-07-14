"""node.py LLM/tool handling — findings [5] and [10]."""

import asyncio

import engine.node as node
from engine.node import _summarize_proposal_for_discussion


def _run(coro):
    return asyncio.run(coro)


def test_summarize_proposal_tolerates_string_spike_document():
    # Finding [10]: an LLM-returned spike_document that is a bare string must not
    # raise AttributeError on doc.get(...).
    parsed = {
        "message_type": "PROPOSAL_REVISION",
        "spike_document": "just a string, not a dict",
        "id": "x",
        "timestamp": "t",
    }
    out = _summarize_proposal_for_discussion(parsed, "agent-1", "m1")
    assert out["message_type"] == "COMMENT"
    assert out["from_agent"] == "agent-1"
    assert out["meeting_id"] == "m1"
    assert isinstance(out["points"], list) and out["points"]


def test_summarize_proposal_uses_doc_fields():
    parsed = {"spike_document": {"proposed_solution": "Do the thing"}}
    out = _summarize_proposal_for_discussion(parsed, "a", "m")
    assert any("Do the thing" in p for p in out["points"])


def test_call_llm_uses_fresh_message_list_each_retry(monkeypatch):
    # Finding [5]: a mid-round failure on attempt 1 (after an assistant tool_calls
    # message is appended) must not corrupt the message list handed to retries.
    received = []

    async def fake_cwt(messages, temperature, max_tokens, tools):
        received.append(list(messages))
        if len(received) == 1:
            messages.append({"role": "assistant", "tool_calls": [{"id": "1"}]})
            raise RuntimeError("truncated tool args")
        return "a sufficiently long valid answer"

    async def no_sleep(*a, **k):
        return None

    monkeypatch.setattr(node, "_completion_with_tools", fake_cwt)
    monkeypatch.setattr(node.asyncio, "sleep", no_sleep)
    node.agent_skills = []
    node.agent_model = "test/model"

    out = _run(node.call_llm("system", "user", 0.5, 100))

    assert out == "a sufficiently long valid answer"
    assert len(received) == 2
    # The failed attempt's dangling tool_calls did NOT leak into attempt 2.
    assert [m["role"] for m in received[1]] == ["system", "user"]


def test_completion_with_tools_handles_malformed_tool_args(monkeypatch):
    # Finding [5] (defensive parse): invalid JSON tool arguments are answered with
    # an error tool result rather than raising and poisoning the sequence.
    class FakeFn:
        name = "web_search"
        arguments = "{not valid json"

    class FakeTC:
        id = "tc1"
        function = FakeFn()

    class FakeMsg:
        def __init__(self, tool_calls, content):
            self.tool_calls = tool_calls
            self.content = content

        def model_dump(self):
            return {"role": "assistant", "tool_calls": [{"id": "tc1"}]}

    class FakeResp:
        def __init__(self, msg):
            self.choices = [type("C", (), {"message": msg})()]

    calls = {"n": 0}

    async def fake_acompletion(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(FakeMsg([FakeTC()], None))
        return FakeResp(FakeMsg(None, "final answer text"))

    monkeypatch.setattr(node.litellm, "acompletion", fake_acompletion)
    node.agent_model = "test/model"

    messages = [{"role": "user", "content": "hi"}]
    out = _run(node._completion_with_tools(messages, 0.5, 100, tools=[{"x": 1}]))

    assert out == "final answer text"
    assert any(
        m.get("role") == "tool" and "could not parse" in m.get("content", "")
        for m in messages
    )
