"""
Pack Validator — Cross-reference checks for meeting pack integrity.

Validates that a meeting pack's JSON files are internally consistent:
agent IDs, role references, model aliases, schema names, and port uniqueness.

Usage:
    python -m engine.validate_pack packs/technical-spike
    python -m engine.validate_pack packs/should-we-open-source --strict
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


class PackError:
    def __init__(self, file: str, message: str, severity: str = "error"):
        self.file = file
        self.message = message
        self.severity = severity

    def __str__(self) -> str:
        tag = "ERROR" if self.severity == "error" else "WARN"
        return f"  [{tag}] {self.file}: {self.message}"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"_parse_error": str(e)}


def validate_pack(pack_dir: Path, strict: bool = False) -> list[PackError]:
    errors: list[PackError] = []
    sev = "error" if strict else "warn"

    profiles_path = pack_dir / "profiles.json"
    template_path = pack_dir / "meeting_template.json"
    prompts_path = pack_dir / "agent_prompts.json"
    schemas_path = pack_dir / "message_schemas.json"

    profiles = _load_json(profiles_path)
    template = _load_json(template_path)
    prompts = _load_json(prompts_path)
    schemas = _load_json(schemas_path)

    if profiles is None:
        errors.append(PackError("profiles.json", "missing (required)"))
        return errors
    if "_parse_error" in profiles:
        errors.append(
            PackError("profiles.json", f"invalid JSON: {profiles['_parse_error']}")
        )
        return errors

    agents = profiles.get("agents", [])
    agent_ids = {a["id"] for a in agents if "id" in a}

    for a in agents:
        if "id" not in a:
            errors.append(PackError("profiles.json", f"agent missing 'id': {a}"))
        if "port" not in a:
            errors.append(
                PackError("profiles.json", f"agent '{a.get('id', '?')}' missing 'port'")
            )
        if "soul" not in a:
            errors.append(
                PackError("profiles.json", f"agent '{a.get('id', '?')}' missing 'soul'")
            )
        if "team" not in a:
            errors.append(
                PackError(
                    "profiles.json", f"agent '{a.get('id', '?')}' missing 'team'", sev
                )
            )

    seen_ports: dict[int, str] = {}
    for a in agents:
        port = a.get("port")
        aid = a.get("id", "?")
        if port is not None:
            if port in seen_ports:
                errors.append(
                    PackError(
                        "profiles.json",
                        f"port {port} used by both '{seen_ports[port]}' and '{aid}'",
                    )
                )
            seen_ports[port] = aid

    litellm_cfg = profiles.get("litellm", {})
    model_map = litellm_cfg.get("model_map", {})
    for a in agents:
        alias = a.get("model")
        if alias and alias not in model_map and "/" not in alias:
            errors.append(
                PackError(
                    "profiles.json",
                    f"agent '{a.get('id', '?')}' uses model alias '{alias}' not in model_map",
                    sev,
                )
            )

    if template is not None and "_parse_error" not in template:
        roles = template.get("roles", {})
        for role_name, ref in roles.items():
            refs = ref if isinstance(ref, list) else [ref]
            for r in refs:
                if r not in agent_ids:
                    errors.append(
                        PackError(
                            "meeting_template.json",
                            f"role '{role_name}' references agent '{r}' not in profiles.json",
                        )
                    )

        phases = template.get("phases", [])
        for phase in phases:
            expected = phase.get("expected_type")
            if expected and schemas and "_parse_error" not in schemas:
                if expected not in schemas and expected != "FINAL_REVIEW":
                    errors.append(
                        PackError(
                            "meeting_template.json",
                            f"phase '{phase.get('id', '?')}' expects schema '{expected}' not in message_schemas.json",
                            sev,
                        )
                    )

            follow_up = phase.get("follow_up", {})
            fu_type = follow_up.get("expected_type")
            if fu_type and schemas and "_parse_error" not in schemas:
                if fu_type not in schemas:
                    errors.append(
                        PackError(
                            "meeting_template.json",
                            f"follow_up expects schema '{fu_type}' not in message_schemas.json",
                            sev,
                        )
                    )

            participants = phase.get("participants", [])
            for p in participants:
                if p not in roles:
                    errors.append(
                        PackError(
                            "meeting_template.json",
                            f"phase '{phase.get('id', '?')}' participant role '{p}' not in template roles",
                            sev,
                        )
                    )
    elif template is not None and "_parse_error" in template:
        errors.append(
            PackError(
                "meeting_template.json", f"invalid JSON: {template['_parse_error']}"
            )
        )

    if prompts is not None and "_parse_error" not in prompts:
        prompt_agents = set(prompts.get("agents", {}).keys())
        for aid in agent_ids:
            if aid not in prompt_agents:
                errors.append(
                    PackError(
                        "agent_prompts.json",
                        f"no prompt defined for agent '{aid}'",
                        sev,
                    )
                )
        for paid in prompt_agents:
            if paid not in agent_ids:
                errors.append(
                    PackError(
                        "agent_prompts.json",
                        f"prompt for '{paid}' but agent not in profiles.json",
                        sev,
                    )
                )
    elif prompts is not None and "_parse_error" in prompts:
        errors.append(
            PackError("agent_prompts.json", f"invalid JSON: {prompts['_parse_error']}")
        )

    if schemas is not None and "_parse_error" in schemas:
        errors.append(
            PackError(
                "message_schemas.json", f"invalid JSON: {schemas['_parse_error']}"
            )
        )

    context_ref = (template or {}).get("context", "")
    if context_ref:
        resolved = (pack_dir / context_ref).resolve()
        if not resolved.exists():
            errors.append(
                PackError(
                    "meeting_template.json",
                    f"context path '{context_ref}' does not exist at {resolved}",
                    sev,
                )
            )

    return errors


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate a meeting pack's cross-references"
    )
    parser.add_argument("pack_dir", type=str, help="Path to meeting pack directory")
    parser.add_argument(
        "--strict", action="store_true", help="Treat warnings as errors"
    )
    args = parser.parse_args()

    pack = Path(args.pack_dir)
    if not pack.is_dir():
        print(f"Error: {pack} is not a directory")
        sys.exit(1)

    errors = validate_pack(pack, strict=args.strict)

    real_errors = [e for e in errors if e.severity == "error"]
    warnings = [e for e in errors if e.severity == "warn"]

    if not errors:
        print(f"✅ {pack.name}: all checks passed")
        return

    print(f"{'❌' if real_errors else '⚠️'}  {pack.name}:")
    for e in errors:
        print(str(e))

    if real_errors:
        print(f"\n{len(real_errors)} error(s), {len(warnings)} warning(s)")
        sys.exit(1)
    else:
        print(f"\n{len(warnings)} warning(s)")


if __name__ == "__main__":
    main()
