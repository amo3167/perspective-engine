"""server/main.py API robustness + standalone paths — findings [12], [14], [15]."""

import json

from fastapi.testclient import TestClient

import server.main as srv

client = TestClient(srv.app)


# ── Finding [15]: null phase in phase_complete broadcast ───────────────────


def test_phase_complete_with_null_phase_does_not_500():
    client.post("/api/meeting/reset")
    resp = client.post(
        "/api/meeting/broadcast",
        json={"meeting_type": "phase_complete", "phase": None},
    )
    assert resp.status_code == 200
    current = client.get("/api/meeting/current").json()
    assert current["phase"] == 1


def test_phase_complete_with_valid_phase_increments():
    client.post("/api/meeting/reset")
    client.post(
        "/api/meeting/broadcast", json={"meeting_type": "phase_complete", "phase": 3}
    )
    assert client.get("/api/meeting/current").json()["phase"] == 4


# ── Finding [14]: a malformed pack must not drop the whole listing ─────────


def _write_pack(pack_dir, template, profiles=None):
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "meeting_template.json").write_text(
        json.dumps(template), encoding="utf-8"
    )
    if profiles is not None:
        (pack_dir / "profiles.json").write_text(json.dumps(profiles), encoding="utf-8")


def test_pack_with_phase_missing_label_is_still_listed(tmp_path, monkeypatch):
    packs_dir = tmp_path / "packs"
    _write_pack(
        packs_dir / "demo",
        # second phase is missing the 'label' key entirely
        {
            "template_name": "demo",
            "phases": [{"phase_number": 1, "label": "Intro"}, {"phase_number": 2}],
        },
        {
            "agents": [{"id": "alice", "role": "author"}, {"role": "reviewer"}]
        },  # 2nd agent missing id
    )
    monkeypatch.setattr(srv, "PACKS_DIR", packs_dir)

    resp = client.get("/api/meeting/packs")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()]
    assert "demo" in names  # not silently dropped by a KeyError
    demo = next(p for p in resp.json() if p["name"] == "demo")
    # The id-less agent is skipped, the valid one is kept.
    assert [a["id"] for a in demo["agents"]] == ["alice"]


# ── Finding [12]: standalone deploy resolves the bundled patterns/ scripts ──


def test_debate_resolves_bundled_script():
    resolved = srv._resolve_debate_run()
    assert resolved is not None
    script, cleanup, cwd, python, env_var = resolved
    assert script.name == "debate_orchestrator.py"
    assert script.is_file()
    assert env_var == "PERSPECTIVE_ENGINE_DEBATE_BACKEND_URL"


def test_feedback_resolves_bundled_script():
    sim_dir, script, output_dir, feature_dir = srv._feedback_sim_paths()
    assert script.name == "feedback_simulator.py"
    assert script.is_file()
    assert "patterns" in script.parts
