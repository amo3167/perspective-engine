"""
Pack Loader — Load and resolve meeting pack configuration files.
"""

from __future__ import annotations

import json
import logging
import os
import glob as glob_mod
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ENGINE_DIR = Path(__file__).resolve().parent

DEFAULT_PROFILES = ENGINE_DIR / "profiles.json"
DEFAULT_PROMPTS = ENGINE_DIR / "agent_prompts.json"
DEFAULT_SCHEMAS = ENGINE_DIR / "message_schemas.json"
DEFAULT_TEMPLATE = ENGINE_DIR / "meeting_template.json"


class MeetingPack:
    """Resolved meeting pack ready for the orchestrator."""

    def __init__(
        self,
        profiles: dict[str, Any],
        template: dict[str, Any],
        prompts_path: Path,
        schemas_path: Path,
        schemas: dict[str, Any],
        agents: list[dict[str, Any]],
        model_map: dict[str, str],
        rules_cfg: dict[str, Any],
        context_dir: str,
        domain_handbook: str,
        pack_dir: Path | None,
    ):
        self.profiles = profiles
        self.template = template
        self.prompts_path = prompts_path
        self.schemas_path = schemas_path
        self.schemas = schemas
        self.agents = agents
        self.model_map = model_map
        self.rules_cfg = rules_cfg
        self.context_dir = context_dir
        self.domain_handbook = domain_handbook
        self.pack_dir = pack_dir

    @property
    def time_limit(self) -> float:
        return self.rules_cfg.get("phase_2_time_limit_seconds", 300)

    @property
    def rules_tips(self) -> list[str]:
        return self.rules_cfg.get("phase_2_general_tips", [])

    @property
    def template_name(self) -> str:
        return self.template.get("template_name", "meeting")

    @property
    def proposal_sections(self) -> list[str]:
        return self.template.get(
            "proposal_sections",
            ["problem_statement", "proposed_solution", "impact_areas", "rollback_strategy", "timeline"],
        )

    @property
    def roles(self) -> dict[str, Any]:
        return self.template.get("roles", {})

    @property
    def phases(self) -> list[dict[str, Any]]:
        return self.template.get("phases", [])

    def phase_by_id(self, phase_id: str) -> dict[str, Any] | None:
        return next((p for p in self.phases if p.get("id") == phase_id), None)

    def phase_by_number(self, number: int) -> dict[str, Any] | None:
        return next((p for p in self.phases if p.get("phase_number") == number), None)

    def resolve_roles(self) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, Any] | None,
        dict[str, Any] | None,
        str | None,
        list[dict[str, Any]],
    ]:
        agent_by_id = {a["id"]: a for a in self.agents}
        roles = self.roles

        facilitator_id = roles.get("facilitator") or next(
            (a["id"] for a in self.agents if a.get("team") == "FACILITATOR"), None
        )
        author_id = roles.get("author") or next(
            (a["id"] for a in self.agents if a.get("team") == "AUTHOR"), None
        )
        architect_id = (
            roles.get("architect")
            or roles.get("decision_maker")
            or next(
                (a["id"] for a in self.agents if a.get("role") in ("architect", "gatekeeper", "decision_maker")),
                None,
            )
        )

        facilitator = agent_by_id.get(facilitator_id)
        author = agent_by_id.get(author_id)
        reviewers = [agent_by_id[rid] for rid in roles.get("reviewers", []) if rid in agent_by_id]
        if not reviewers:
            reviewers = [a for a in self.agents if a.get("team") == "REVIEWERS"]

        return agent_by_id, facilitator, author, architect_id, reviewers


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_context_handbook(path: str) -> tuple[str, str]:
    """Load a handbook and resolve the context directory.

    Returns (handbook_text, context_dir).
    """
    if not path or not os.path.exists(path):
        return "", ""

    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read(), ""

    if os.path.isdir(path):
        readme = os.path.join(path, "README.md")
        handbook = ""
        if os.path.isfile(readme):
            with open(readme, "r", encoding="utf-8") as f:
                handbook = f.read()
            logger.info(f"Loaded handbook README.md ({len(handbook)} bytes) from {path}")
        else:
            md_files = sorted(glob_mod.glob(os.path.join(path, "*.md")))
            listing = "\n".join(f"- {os.path.basename(fp)}" for fp in md_files)
            handbook = f"# Available reference files\n\n{listing}"
            logger.info(f"No README.md; generated file listing ({len(md_files)} files)")
        return handbook, os.path.abspath(path)

    return "", ""


def load_pack(
    pack_dir: str = "",
    context_path: str = "",
) -> MeetingPack:
    """Load a meeting pack from disk and resolve all paths."""

    pack = Path(pack_dir) if pack_dir else None
    profiles_path = (pack / "profiles.json") if pack else DEFAULT_PROFILES
    prompts_path = (pack / "agent_prompts.json") if pack else DEFAULT_PROMPTS
    schemas_path = (pack / "message_schemas.json") if pack else DEFAULT_SCHEMAS
    template_path = (pack / "meeting_template.json") if pack else DEFAULT_TEMPLATE

    if pack:
        logger.info(f"Using meeting pack: {pack}")

    if not profiles_path.exists():
        raise FileNotFoundError(f"profiles.json not found at {profiles_path}")

    profiles = _load_json(profiles_path)
    template = _load_json(template_path)
    schemas = _load_json(schemas_path)

    agents = profiles.get("agents", [])
    backend_cfg = profiles.get("litellm") or profiles.get("bedrock", {})
    model_map = backend_cfg.get("model_map", {})
    rules_cfg = profiles.get("rules", {})

    if template_path.exists():
        logger.info(f"Loaded meeting template: {template.get('template_name', 'unknown')}")

    domain_handbook = ""
    context_dir = ""

    if context_path:
        domain_handbook, context_dir = load_context_handbook(context_path)
    elif pack:
        tmpl_context = template.get("context", "")
        if tmpl_context:
            resolved = (pack / tmpl_context).resolve()
            if resolved.is_dir():
                domain_handbook, context_dir = load_context_handbook(str(resolved))
                logger.info(f"Resolved context from template: {resolved}")
        if not context_dir:
            pack_context = pack / "context"
            if pack_context.is_dir():
                domain_handbook, context_dir = load_context_handbook(str(pack_context))
                logger.info(f"Using default context from meeting pack: {pack_context}")

    return MeetingPack(
        profiles=profiles,
        template=template,
        prompts_path=prompts_path,
        schemas_path=schemas_path,
        schemas=schemas,
        agents=agents,
        model_map=model_map,
        rules_cfg=rules_cfg,
        context_dir=context_dir,
        domain_handbook=domain_handbook,
        pack_dir=pack,
    )
