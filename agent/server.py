"""Minimal web server for the World Cup 2026 fan-logistics agent (Cloud Run).

Wraps the existing `root_agent` (tools, eval, self-improvement loop unchanged) in a
single-page UI + JSON endpoint so hackathon judges can open a URL and run a planning
turn. Each request runs one ADK turn, fully traced to Phoenix (project worldcup-agent).

Config comes entirely from environment variables (set as Cloud Run env vars / secrets):
GEMINI_MODEL, GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION=global, GOOGLE_GENAI_USE_VERTEXAI=1,
PHOENIX_API_KEY, PHOENIX_COLLECTOR_ENDPOINT, PHOENIX_PROJECT_NAME. Nothing is baked in.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# Local dev convenience only; on Cloud Run there is no .env and this is a no-op.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from google.adk.runners import InMemoryRunner
from google.genai import types

from instrumentation import setup_tracing
from worldcup_agent.agent import root_agent

APP_NAME = "worldcup_web"
_runner: InMemoryRunner | None = None


def _get_runner() -> InMemoryRunner:
    global _runner
    if _runner is None:
        setup_tracing()
        _runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
    return _runner


app = FastAPI(title="World Cup 2026 Fan-Logistics Agent")


class PlanRequest(BaseModel):
    message: str


async def _run_turn(message: str) -> str:
    runner = _get_runner()
    user_id, session_id = "judge", secrets.token_hex(8)
    await runner.session_service.create_session(
        app_name=APP_NAME, user_id=user_id, session_id=session_id)
    chunks: list[str] = []
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id,
        new_message=types.Content(role="user", parts=[types.Part(text=message)]),
    ):
        if event.content and event.content.parts:
            for part in event.content.parts:
                if getattr(part, "text", None):
                    chunks.append(part.text)
    return "".join(chunks).strip()


# Note: use /status, NOT /healthz — the Google Front End intercepts the literal
# /healthz path before it reaches the container, returning a Google 404.
@app.get("/status")
def status() -> dict:
    return {
        "status": "ok",
        "model": os.environ.get("GEMINI_MODEL", "unset"),
        "location": os.environ.get("GOOGLE_CLOUD_LOCATION", "unset"),
        "phoenix_project": os.environ.get("PHOENIX_PROJECT_NAME", "unset"),
        "revision": os.environ.get("K_REVISION", "local"),
        "tools": [getattr(t, "name", type(t).__name__) for t in root_agent.tools],
    }


@app.post("/plan")
async def plan(req: PlanRequest) -> JSONResponse:
    if not req.message.strip():
        return JSONResponse({"error": "message is required"}, status_code=400)
    try:
        answer = await _run_turn(req.message.strip())
        return JSONResponse({"plan": answer})
    except Exception as e:  # surface errors to the caller instead of a bare 500
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)


_EXAMPLES = [
    "Plan my match day at SoFi Stadium. Kickoff is 16:00. Budget $60 per person.",
    "Plan a match day at MetLife Stadium, kickoff 15:00, budget $90 per person.",
    "Review your recent plan evaluations, then plan SoFi Stadium (16:00, $60) without repeating past mistakes.",
]


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    opts = "".join(f"<option>{e}</option>" for e in _EXAMPLES)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>World Cup 2026 Fan-Logistics Agent</title>
<style>
 body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#111}}
 h1{{font-size:1.4rem}} .sub{{color:#555;margin-top:-.5rem}}
 textarea{{width:100%;height:90px;font-size:1rem;padding:.6rem;box-sizing:border-box}}
 button{{font-size:1rem;padding:.6rem 1.2rem;margin-top:.6rem;cursor:pointer}}
 select{{width:100%;padding:.4rem;margin:.4rem 0}}
 pre{{white-space:pre-wrap;background:#f6f6f6;padding:1rem;border-radius:8px;margin-top:1rem}}
 .muted{{color:#777;font-size:.85rem}}
</style></head><body>
<h1>⚽ World Cup 2026 Fan-Logistics Agent</h1>
<p class="sub">Gemini 3.1 · Google ADK · traced + self-evaluated in Arize Phoenix</p>
<label class="muted">Examples (pick one to fill the box):</label>
<select id="ex" onchange="document.getElementById('msg').value=this.value">{opts}</select>
<textarea id="msg" placeholder="e.g. Plan my match day at SoFi Stadium, kickoff 16:00, budget $60 per person."></textarea>
<button onclick="go()">Plan my match day</button>
<span id="status" class="muted"></span>
<pre id="out"></pre>
<script>
async function go(){{
  const msg=document.getElementById('msg').value.trim();
  if(!msg)return;
  const s=document.getElementById('status'), out=document.getElementById('out');
  s.textContent=' running (this takes ~15-30s)...'; out.textContent='';
  try{{
    const r=await fetch('/plan',{{method:'POST',headers:{{'Content-Type':'application/json'}},
      body:JSON.stringify({{message:msg}})}});
    const j=await r.json();
    out.textContent = j.plan || j.error || JSON.stringify(j);
  }}catch(e){{out.textContent='Request failed: '+e;}}
  s.textContent='';
}}
document.getElementById('msg').value=document.getElementById('ex').value;
</script>
</body></html>"""
