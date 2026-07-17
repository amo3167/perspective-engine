"""node.py pure parsing/validation helpers for (messy) LLM output."""

from engine.node import (
    _detect_repetition,
    _extract_nested_json_from_points,
    _format_transcript_for_prompt,
    _normalize_field_aliases,
    _parse_json_response,
    _unwrap_content_object,
    _validate_and_fill,
)


def test_parse_json_plain():
    assert _parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_markdown_fenced():
    assert _parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_embedded_in_prose():
    assert _parse_json_response('Here you go: {"a": 1} — done') == {"a": 1}


def test_parse_json_invalid_returns_empty():
    assert _parse_json_response("not json at all") == {}
    assert _parse_json_response("") == {}


def test_unwrap_message_type_wrapper():
    parsed = {"CHANGE_REQUEST": {"message_type": "CHANGE_REQUEST", "changes": []}}
    assert _unwrap_content_object(parsed) == {
        "message_type": "CHANGE_REQUEST",
        "changes": [],
    }


def test_unwrap_content_wrapper():
    parsed = {"content": {"message_type": "COMMENT", "points": []}}
    assert _unwrap_content_object(parsed)["message_type"] == "COMMENT"


def test_unwrap_passthrough_when_not_wrapped():
    parsed = {"message_type": "COMMENT", "points": ["x"]}
    assert _unwrap_content_object(parsed) is parsed


def test_unwrap_non_dict_returned_unchanged():
    assert _unwrap_content_object(["not", "a", "dict"]) == ["not", "a", "dict"]


def test_extract_nested_json_from_points_plain():
    parsed = {"points": ['{"message_type": "COMMENT", "x": 1}']}
    assert _extract_nested_json_from_points(parsed, "COMMENT") == {
        "message_type": "COMMENT",
        "x": 1,
    }


def test_extract_nested_json_from_points_fenced_and_prose():
    parsed = {"points": ['prefix ```{"message_type": "AGREE"}``` suffix']}
    out = _extract_nested_json_from_points(parsed, "AGREE")
    assert out == {"message_type": "AGREE"}


def test_extract_nested_json_from_points_none_when_absent():
    assert (
        _extract_nested_json_from_points({"points": ["just prose"]}, "COMMENT") is None
    )
    assert _extract_nested_json_from_points({"points": "notalist"}, "COMMENT") is None


def test_normalize_aliases_spike_document():
    msg = {"message_type": "PROPOSAL_REVISION", "spike_document": {"title": "T"}}
    _normalize_field_aliases(msg)
    assert "spike_document" not in msg
    assert msg["updated_spike_document"] == {"title": "T"}


def test_normalize_aliases_change_request_variants():
    for alias in ("change_requests", "required_changes"):
        msg = {"message_type": "CHANGE_REQUEST", alias: [{"c": 1}]}
        _normalize_field_aliases(msg)
        assert msg["changes"] == [{"c": 1}]
        assert alias not in msg


def test_validate_and_fill_requires_decision_for_approval():
    assert _validate_and_fill({"message_type": "ARCHITECT_APPROVAL"}) is False
    ok = {"message_type": "ARCHITECT_APPROVAL", "decision": "APPROVE"}
    assert _validate_and_fill(ok) is True


def test_validate_and_fill_populates_defaults():
    msg = {"message_type": "MEETING_NOTES"}
    assert _validate_and_fill(msg) is True
    assert msg["executive_summary"] == ""
    assert msg["decisions"] == []
    assert msg["audit_trail"] == []


def test_format_transcript_renders_string_and_dict_content():
    transcript = [
        {"from_agent": "alice", "message_type": "COMMENT", "content": "hello"},
        {"name": "bob", "message_type": "AGREE", "content": {"points": ["ok"]}},
    ]
    out = _format_transcript_for_prompt(transcript)
    assert "[alice] (COMMENT): hello" in out
    assert "[bob] (AGREE):" in out
    assert '"points"' in out  # dict content was json-encoded


def test_detect_repetition_warns_on_circular_themes():
    entries = [{"content": "blocker latency scalability"} for _ in range(6)]
    assert "CONVERGENCE WARNING" in _detect_repetition(entries)


def test_detect_repetition_reads_dict_points():
    entries = [
        {"content": {"points": ["blocker latency scalability concern"]}}
        for _ in range(6)
    ]
    assert "CONVERGENCE WARNING" in _detect_repetition(entries)


def test_detect_repetition_empty_for_short_or_varied():
    assert _detect_repetition([{"content": "x"}] * 3) == ""  # fewer than 6 entries
    varied = [{"content": f"unique{i} distinct{i} separate{i}"} for i in range(6)]
    assert _detect_repetition(varied) == ""  # no theme repeats often enough
