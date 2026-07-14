"""Re-export engine.agent_tools (standalone PE) with monorepo fallback."""

from __future__ import annotations

import sys
from pathlib import Path

_pe = Path(__file__).resolve().parents[3]
_repo = Path(__file__).resolve().parents[4]
for _p in (_pe, _repo):
    _s = str(_p)
    if _s not in sys.path:
        sys.path.insert(0, _s)

try:
    from engine.agent_tools import (  # noqa: F401
        ToolEntry,
        TOOL_REGISTRY,
        web_search,
        read_reference_file,
        WEB_SEARCH_SPEC,
        READ_REFERENCE_FILE_SPEC,
        register_tool,
        get_registered_skills,
        build_tool_config,
        get_tool_descriptions,
        execute_tool,
        build_tool_result_message,
        set_reference_context_dir,
    )
except ImportError:
    from agent_boxes.agent_tools import (  # noqa: F401
        ToolEntry,
        TOOL_REGISTRY,
        web_search,
        read_reference_file,
        WEB_SEARCH_SPEC,
        READ_REFERENCE_FILE_SPEC,
        register_tool,
        get_registered_skills,
        build_tool_config,
        get_tool_descriptions,
        execute_tool,
        build_tool_result_message,
        set_reference_context_dir,
    )
