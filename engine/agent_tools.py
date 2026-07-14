"""
Agent Tools — Tool registry and execution engine for meeting agents.

Each tool is registered under a skill name that matches the agent's `skills`
list in profiles.json. Agents only get access to the tools listed in their profile.
"""

import os
import logging
from dataclasses import dataclass
from typing import Any, Callable

from engine.runtime import ssl_verify_enabled

logger = logging.getLogger("agent_tools")


@dataclass
class ToolEntry:
    skill_name: str
    spec: dict[str, Any]
    fn: Callable[..., str]
    description: str


def web_search(query: str, max_results: int = 3) -> str:
    """DuckDuckGo search for real-time information."""
    try:
        return _ddg_html_search(query, max_results)
    except Exception as e:
        logger.error(f"Web search error: {e}")
        return f"Search error: {e}"


def _ddg_html_search(query: str, max_results: int = 3) -> str:
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        verify=ssl_verify_enabled(),
        timeout=15,
        follow_redirects=True,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    result_blocks = soup.select(".result__body")
    if not result_blocks:
        return "No search results found."
    formatted = f"Web Search Results for '{query}':\n\n"
    for block in result_blocks[:max_results]:
        title_el = block.select_one(".result__a")
        snippet_el = block.select_one(".result__snippet")
        title = title_el.get_text(strip=True) if title_el else ""
        raw_href = title_el.get("href", "") if title_el else ""
        href = _extract_ddg_url(raw_href if isinstance(raw_href, str) else "")
        snippet = snippet_el.get_text(strip=True) if snippet_el else ""
        formatted += f"- {title}\n  {href}\n  {snippet}\n\n"
    return formatted


def _extract_ddg_url(raw: str) -> str:
    from urllib.parse import urlparse, parse_qs, unquote

    if "uddg=" in raw:
        parsed = parse_qs(urlparse(raw).query)
        return unquote(parsed.get("uddg", [raw])[0])
    return raw


_reference_context_dir: str = ""
MAX_FILE_READ_BYTES = 15_000


def set_reference_context_dir(path: str) -> None:
    global _reference_context_dir
    _reference_context_dir = path


def read_reference_file(filename: str) -> str:
    """Read a reference document from the configured context directory."""
    if not _reference_context_dir:
        return "Error: No reference directory configured for this meeting."
    safe_name = os.path.basename(filename)
    filepath = os.path.join(_reference_context_dir, safe_name)
    if not os.path.isfile(filepath):
        available = [f for f in os.listdir(_reference_context_dir) if f.endswith(".md")]
        return f"File '{safe_name}' not found. Available files: {', '.join(sorted(available))}"
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()
    if len(content) > MAX_FILE_READ_BYTES:
        content = content[:MAX_FILE_READ_BYTES] + "\n\n... (truncated at 15KB)"
    logger.info(f"Tool read_reference_file: {safe_name} ({len(content)} bytes)")
    return content


WEB_SEARCH_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": "web_search",
        "description": (
            "Search the internet for real-world examples, case studies, industry "
            "precedents, current best practices, or any external evidence relevant "
            "to the discussion."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query"}
                },
                "required": ["query"],
            }
        },
    }
}

READ_REFERENCE_FILE_SPEC: dict[str, Any] = {
    "toolSpec": {
        "name": "read_reference_file",
        "description": (
            "Read a reference document from the meeting's reference directory. "
            "Pass just the filename (e.g. 'context.md')."
        ),
        "inputSchema": {
            "json": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Filename to read"}
                },
                "required": ["filename"],
            }
        },
    }
}


TOOL_REGISTRY: dict[str, ToolEntry] = {
    "web_search": ToolEntry(
        skill_name="web_search",
        spec=WEB_SEARCH_SPEC,
        fn=web_search,
        description="Search the internet for real-time information",
    ),
    "read_reference_file": ToolEntry(
        skill_name="read_reference_file",
        spec=READ_REFERENCE_FILE_SPEC,
        fn=read_reference_file,
        description="Read a reference document from the meeting's context directory",
    ),
}


def register_tool(
    skill_name: str,
    spec: dict[str, Any],
    fn: Callable[..., str],
    description: str,
) -> None:
    TOOL_REGISTRY[skill_name] = ToolEntry(
        skill_name=skill_name,
        spec=spec,
        fn=fn,
        description=description,
    )


def get_registered_skills() -> list[str]:
    return list(TOOL_REGISTRY.keys())


def build_tool_config(skills: list[str]) -> dict[str, Any] | None:
    tools = [TOOL_REGISTRY[name].spec for name in skills if name in TOOL_REGISTRY]
    if not tools:
        return None
    return {"tools": tools}


def get_tool_descriptions(skills: list[str]) -> list[dict[str, str]]:
    return [
        {"name": name, "description": TOOL_REGISTRY[name].description}
        for name in skills
        if name in TOOL_REGISTRY
    ]


def build_tool_result_message(
    tool_use_blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    result_content: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []

    for block in tool_use_blocks:
        tu = block["toolUse"]
        tool_name = tu["name"].strip()
        tu["name"] = tool_name
        tool_input = tu["input"]
        tool_use_id = tu["toolUseId"]

        logger.info(f"  Executing tool: {tool_name}({tool_input})")
        result_text = execute_tool(tool_name, tool_input)

        result_content.append(
            {
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "content": [{"text": result_text[:3000]}],
                }
            }
        )
        traces.append(
            {
                "tool": tool_name,
                "input": tool_input,
                "result_preview": result_text[:500],
            }
        )

    return {
        "message": {"role": "user", "content": result_content},
        "traces": traces,
    }


def build_litellm_tools(skills: list[str]) -> list[dict[str, Any]] | None:
    tools: list[dict[str, Any]] = []
    for name in skills:
        entry = TOOL_REGISTRY.get(name)
        if not entry:
            continue
        bedrock_spec = entry.spec["toolSpec"]
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": bedrock_spec["name"],
                    "description": bedrock_spec["description"],
                    "parameters": bedrock_spec["inputSchema"]["json"],
                },
            }
        )
    return tools or None


def execute_tool(name: str, input_data: dict[str, Any]) -> str:
    entry = TOOL_REGISTRY.get(name.strip())
    if entry is None:
        return f"Unknown tool: {name}"
    try:
        return entry.fn(**input_data)
    except Exception as e:
        logger.error(f"Tool execution error ({name}): {e}")
        return f"Tool error: {e}"
