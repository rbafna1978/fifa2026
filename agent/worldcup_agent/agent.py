"""World Cup 2026 fan-logistics agent (ADK + Gemini 3.1 + Phoenix tracing)."""
from __future__ import annotations

import os
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools import FunctionTool, google_search
from google.adk.tools.agent_tool import AgentTool
from dotenv import load_dotenv

from instrumentation import setup_tracing
from worldcup_agent.prompt import worldcup_agent_instruction
from worldcup_agent.tools import get_match_logistics, find_food_near, build_day_plan

# Load env + start tracing for both `python main.py` and `adk run worldcup_agent`.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
setup_tracing()

_model = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")

# google_search is a built-in tool and cannot share an agent with function tools.
# The supported workaround: wrap it in its own agent, exposed via AgentTool.
search_agent = Agent(
    model=_model,
    name="live_search",
    description=(
        "Searches the live web for current World Cup 2026 facts: match fixtures, "
        "kickoff times, venue advisories, and weather."
    ),
    instruction=(
        "You are a live web-search specialist for World Cup 2026 fans. Given a query, "
        "use Google Search to find current, factual information and return a concise, "
        "factual summary. No fluff, no speculation."
    ),
    tools=[google_search],
)

root_agent = Agent(
    model=_model,
    name="worldcup_fan_logistics",
    instruction=worldcup_agent_instruction,
    tools=[
        FunctionTool(func=get_match_logistics),
        FunctionTool(func=find_food_near),
        FunctionTool(func=build_day_plan),
        AgentTool(agent=search_agent),
    ],
)
