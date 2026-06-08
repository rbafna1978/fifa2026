"""Bounded Phoenix MCP toolset for the self-reflection agent.

The reflection agent introspects the worldcup-agent's OWN runs through the real
`@arizeai/phoenix-mcp` server. Left unbounded, that path is unstable: the
`list-traces` / `get-trace` tools embed *entire* span bodies — full LLM
inputs/outputs plus google_search grounding chunks — with no per-span cap. A
single call can exceed Gemini's 1,048,576-token input limit (the
`400 INVALID_ARGUMENT "input token count exceeds..."` we were hitting) and even
OOM the MCP stdio client (multi-GB JSON) before the model is ever reached.

This wrapper keeps the agent on the *real* Phoenix MCP server but makes the
reflection path small and stable by:

  1. Exposing only lightweight, bounded tools via a correct ``tool_filter``
     (verified against the live server's tool list) — never the unbounded
     trace-dump tools ``list-traces`` / ``get-trace``.
  2. Clamping the ``limit`` argument so one call can't request a huge page.
  3. Pruning every span in the result down to summary fields (name, kind,
     latency, status, tool name, token counts, eval scores) and dropping the
     heavy ``input.value`` / ``output.value`` message bodies — deterministically,
     regardless of how the model phrases its query.
  4. Enforcing a final hard character cap as a last-resort guard.

Net effect: the agent reads its own traces over MCP and gets back a compact,
structured summary every time.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.tools.mcp_tool.mcp_tool import MCPTool
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.tool_context import ToolContext

logger = logging.getLogger("google_adk.worldcup_agent.phoenix_reflection")

# Only these (verified) tool names are exposed to the reflection agent. They are
# all either inherently tiny or bounded by a `limit` arg. The unbounded
# `list-traces` / `get-trace` dump tools are deliberately excluded.
SAFE_TOOLS = ["list-projects", "get-spans", "get-span-annotations"]

# Hard ceiling on any `limit` arg the model passes (these tools default much
# higher — get-spans defaults to 100, allows up to 1000).
MAX_LIMIT = 10

# Final guard: cap the serialized result the model receives (~ a few K tokens).
MAX_RESULT_CHARS = 24_000

# Span attribute keys worth keeping for reflection. Everything else (notably the
# large `input.value` / `output.value` / `*.messages` bodies) is dropped.
_KEEP_ATTR_SUBSTRINGS = (
    "tool.name",
    "tool.description",
    "token_count",
    "llm.model_name",
    "openinference.span.kind",
    "metadata",
)
# Even an allowed key is dropped if its value is this long (defensive).
_MAX_ATTR_VALUE_CHARS = 240


def _prune_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    kept: dict[str, Any] = {}
    for key, value in attributes.items():
        if not any(sub in key for sub in _KEEP_ATTR_SUBSTRINGS):
            continue
        if len(str(value)) > _MAX_ATTR_VALUE_CHARS:
            continue
        kept[key] = value
    return kept


def _prune_span(span: dict[str, Any]) -> dict[str, Any]:
    pruned = {
        k: span[k]
        for k in (
            "id",
            "name",
            "span_kind",
            "parent_id",
            "start_time",
            "end_time",
            "status_code",
            "status_message",
        )
        if k in span
    }
    attrs = span.get("attributes")
    if isinstance(attrs, dict):
        slim = _prune_attributes(attrs)
        if slim:
            pruned["attributes"] = slim
    return pruned


def _prune_payload(payload: Any) -> Any:
    """Walk a parsed get-spans / get-trace style payload and slim every span."""
    if isinstance(payload, dict):
        if "spans" in payload and isinstance(payload["spans"], list):
            payload = dict(payload)
            payload["spans"] = [_prune_span(s) for s in payload["spans"]]
            return payload
        # A single span object.
        if "span_kind" in payload or ("attributes" in payload and "name" in payload):
            return _prune_span(payload)
        return payload
    if isinstance(payload, list):
        return [_prune_payload(item) for item in payload]
    return payload


def _prune_text_block(text: str) -> str:
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        return text[:MAX_RESULT_CHARS]
    pruned = _prune_payload(parsed)
    out = json.dumps(pruned, ensure_ascii=False)
    if len(out) > MAX_RESULT_CHARS:
        out = out[:MAX_RESULT_CHARS] + ' ...[truncated]"}'
    return out


class _BoundedMCPTool(MCPTool):
    """MCPTool that clamps `limit` and prunes span bodies from the result."""

    async def run_async(self, *, args: dict[str, Any], tool_context: ToolContext) -> Any:
        args = dict(args or {})
        if "limit" in args:
            try:
                args["limit"] = min(int(args["limit"]), MAX_LIMIT)
            except (TypeError, ValueError):
                args["limit"] = MAX_LIMIT
        elif self.name == "get-spans":
            args["limit"] = MAX_LIMIT

        result = await super().run_async(args=args, tool_context=tool_context)
        return _prune_result(result)


def _prune_result(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    content = result.get("content")
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and "text" in block:
                block["text"] = _prune_text_block(block["text"])
    # Some MCP tools also echo a structuredContent dict; drop it to avoid the
    # model seeing the un-pruned copy.
    if "structuredContent" in result:
        result["structuredContent"] = {"note": "omitted; see pruned text content"}
    return result


class BoundedPhoenixToolset(McpToolset):
    """McpToolset that returns `_BoundedMCPTool`s for the safe tool set."""

    async def get_tools(self, readonly_context=None):  # noqa: ANN001
        tools = await super().get_tools(readonly_context)
        for tool in tools:
            if isinstance(tool, MCPTool):
                # Same fields as MCPTool; only run_async behavior changes.
                tool.__class__ = _BoundedMCPTool
        return tools
