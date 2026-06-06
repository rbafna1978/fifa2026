"""World Cup 2026 fan-logistics agent (ADK + Gemini 3.1 + Phoenix tracing)."""
from __future__ import annotations

import os
from pathlib import Path

from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from dotenv import load_dotenv

from instrumentation import setup_tracing
from worldcup_agent.prompt import worldcup_agent_instruction
from worldcup_agent.tools import get_match_logistics, find_food_near, build_day_plan

# Load env + start tracing for both `python main.py` and `adk run worldcup_agent`.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
setup_tracing()

_model = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")

root_agent = Agent(
    model=_model,
    name="worldcup_fan_logistics",
    instruction=worldcup_agent_instruction,
    tools=[
        FunctionTool(func=get_match_logistics),
        FunctionTool(func=find_food_near),
        FunctionTool(func=build_day_plan),
    ],
)
