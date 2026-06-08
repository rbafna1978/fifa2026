"""World Cup 2026 fan-logistics agent (ADK + Gemini 3.1 + Phoenix tracing + Phoenix MCP)."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools import FunctionTool, google_search
from google.adk.tools.agent_tool import AgentTool
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters
from dotenv import load_dotenv

from eval import read_eval_history
from instrumentation import setup_tracing
from worldcup_agent.phoenix_reflection import BoundedPhoenixToolset, SAFE_TOOLS
from worldcup_agent.prompt import worldcup_agent_instruction
from worldcup_agent.reflection_prompt import reflection_instruction
from worldcup_agent.tools import get_match_logistics, find_food_near, build_day_plan

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
setup_tracing()

_model = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")
_phoenix_base = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "")
_phoenix_key = os.environ.get("PHOENIX_API_KEY", "")

# --- Live web search (built-in tool, isolated in its own agent) ---
search_agent = Agent(
    model=_model,
    name="live_search",
    description=("Searches the live web for current World Cup 2026 facts: fixtures, "
                 "kickoff times, venue advisories, and weather."),
    instruction=("Use Google Search to find current, factual information for World Cup 2026 "
                 "fans and return a concise summary. No speculation."),
    tools=[google_search],
)

_tools = [
    FunctionTool(func=get_match_logistics),
    FunctionTool(func=find_food_near),
    FunctionTool(func=build_day_plan),
    FunctionTool(func=read_eval_history),
    AgentTool(agent=search_agent),
]

# --- Phoenix MCP isolated in a reflection agent. `tool_filter` exposes ONLY the
# verified, bounded summary tools (never the unbounded list-traces/get-trace dump
# tools), and BoundedPhoenixToolset clamps `limit` and prunes heavy span bodies so
# the reflection result never overflows the model context. See phoenix_reflection.py.
#
# The Phoenix MCP server runs over `npx`, which exists locally but NOT in the default
# Python Cloud Run container. The live self-improvement loop uses the direct Phoenix
# read (`read_eval_history`), so we add the MCP `reflection` tool ONLY when npx is
# present — otherwise the agent degrades gracefully (no MCP tool) instead of crashing. ---
if shutil.which("npx"):
    phoenix_mcp = BoundedPhoenixToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=["-y", "@arizeai/phoenix-mcp@latest",
                      "--baseUrl", _phoenix_base, "--apiKey", _phoenix_key],
                env={"PHOENIX_API_KEY": _phoenix_key},
            ),
            timeout=25,
        ),
        tool_filter=SAFE_TOOLS,
    )
    reflection_agent = Agent(
        model=_model,
        name="reflection",
        description=("Inspects the agent's OWN recent runs in Phoenix (tool calls, latency, "
                     "evaluations) and reports findings concisely."),
        instruction=reflection_instruction,
        tools=[phoenix_mcp],
    )
    _tools.append(AgentTool(agent=reflection_agent))

root_agent = Agent(
    model=_model,
    name="worldcup_fan_logistics",
    instruction=worldcup_agent_instruction,
    tools=_tools,
)
