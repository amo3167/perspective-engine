"""pack_loader.py — MeetingPack accessors, role resolution, and loaders."""

import json
import os
from pathlib import Path

from engine.pack_loader import MeetingPack, _load_json, load_context_handbook


def _pack(template=None, rules_cfg=None, agents=None):
    return MeetingPack(
        profiles={},
        template=template or {},
        prompts_path=Path("p"),
        schemas_path=Path("s"),
        schemas={},
        agents=agents or [],
        model_map={},
        rules_cfg=rules_cfg or {},
        context_dir="",
        domain_handbook="",
        pack_dir=None,
    )


def test_time_limit_default_and_override():
    assert _pack().time_limit == 300
    assert _pack(rules_cfg={"phase_2_time_limit_seconds": 120}).time_limit == 120


def test_rules_tips_and_template_name():
    assert _pack().rules_tips == []
    assert _pack().template_name == "meeting"
    assert _pack(template={"template_name": "spike"}).template_name == "spike"


def test_proposal_sections_default_and_override():
    assert "problem_statement" in _pack().proposal_sections
    assert _pack(template={"proposal_sections": ["a", "b"]}).proposal_sections == [
        "a",
        "b",
    ]


def test_phase_lookup_by_id_and_number():
    tmpl = {
        "phases": [
            {"id": "intro", "phase_number": 1},
            {"id": "wrap", "phase_number": 2},
        ]
    }
    p = _pack(template=tmpl)
    assert p.phase_by_id("wrap")["phase_number"] == 2
    assert p.phase_by_number(1)["id"] == "intro"
    assert p.phase_by_id("missing") is None
    assert p.phase_by_number(99) is None


def test_resolve_roles_via_roles_dict():
    agents = [{"id": x} for x in ("f1", "a1", "arch1", "r1", "r2")]
    tmpl = {
        "roles": {
            "facilitator": "f1",
            "author": "a1",
            "architect": "arch1",
            "reviewers": ["r1", "r2"],
        }
    }
    _by_id, fac, author, arch_id, reviewers = _pack(
        template=tmpl, agents=agents
    ).resolve_roles()
    assert fac["id"] == "f1"
    assert author["id"] == "a1"
    assert arch_id == "arch1"
    assert [r["id"] for r in reviewers] == ["r1", "r2"]


def test_resolve_roles_via_team_fallback():
    agents = [
        {"id": "f", "team": "FACILITATOR"},
        {"id": "a", "team": "AUTHOR"},
        {"id": "g", "role": "gatekeeper"},
        {"id": "rv", "team": "REVIEWERS"},
    ]
    _by_id, fac, author, arch_id, reviewers = _pack(agents=agents).resolve_roles()
    assert fac["id"] == "f"
    assert author["id"] == "a"
    assert arch_id == "g"
    assert [r["id"] for r in reviewers] == ["rv"]


def test_load_json_reads_and_tolerates_missing(tmp_path):
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"k": 1}), encoding="utf-8")
    assert _load_json(p) == {"k": 1}
    assert _load_json(tmp_path / "missing.json") == {}


def test_load_context_handbook_empty_file_and_dir(tmp_path):
    assert load_context_handbook("") == ("", "")

    f = tmp_path / "hb.md"
    f.write_text("# Handbook", encoding="utf-8")
    text, ctx = load_context_handbook(str(f))
    assert text == "# Handbook" and ctx == ""

    d = tmp_path / "ctx"
    d.mkdir()
    (d / "README.md").write_text("readme body", encoding="utf-8")
    text, ctx = load_context_handbook(str(d))
    assert "readme body" in text
    assert ctx == os.path.abspath(str(d))


def test_load_context_handbook_dir_without_readme_lists_files(tmp_path):
    d = tmp_path / "ctx2"
    d.mkdir()
    (d / "notes.md").write_text("x", encoding="utf-8")
    text, _ctx = load_context_handbook(str(d))
    assert "notes.md" in text  # generated file listing
