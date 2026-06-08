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
from worldcup_agent.tools import KNOWN_VENUES

APP_NAME = "worldcup_web"
_DIETARY_CHOICES = ["", "vegan", "vegetarian", "halal", "gluten_free"]
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


class FormRequest(BaseModel):
    venue: str
    kickoff: str
    budget: int
    is_knockout: bool = False
    tickets_paid: bool = True
    dietary: str = ""
    accessibility_needs: bool = False
    want_post_game_stop: bool = False


def compose_message(f: FormRequest) -> str:
    """Compose the structured form into the natural-language request the agent already
    expects. Done server-side so the composed (clean) message is what gets traced."""
    parts = [
        f"Plan my match day at {f.venue}.",
        f"Kickoff is {f.kickoff}.",
        f"Budget {f.budget} dollars per person.",
        "This is a knockout match (it could go to extra time and penalties)."
        if f.is_knockout else "This is a group-stage match.",
        "My match tickets are already paid for, so the budget is for transit, food and any "
        "post-game stop." if f.tickets_paid else
        "I have not bought match tickets yet (do not include ticket price in the budget).",
    ]
    if f.dietary:
        parts.append(f"I need {f.dietary.replace('_', '-')} food.")
    if f.accessibility_needs:
        parts.append("I have accessibility needs — please surface accessible parking, the "
                     "accessible entrance, and accessible transit/drop-off for the venue.")
    if f.want_post_game_stop:
        parts.append("I also want a post-game dessert/food stop — check it would still be open "
                     "given the realistic match end time.")
    return " ".join(parts)


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


@app.post("/plan-form")
async def plan_form(form: FormRequest) -> JSONResponse:
    """Structured-form entry point: compose the fields into a message, then run the SAME
    traced turn as /plan (agent invocation + tracing are unchanged)."""
    if form.venue not in KNOWN_VENUES:
        return JSONResponse({"error": f"Unknown venue '{form.venue}'."}, status_code=400)
    message = compose_message(form)
    try:
        answer = await _run_turn(message)
        return JSONResponse({"message": message, "plan": answer})
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}", "message": message},
                            status_code=500)


_DIETARY_LABELS = {"": "No preference", "vegan": "Vegan", "vegetarian": "Vegetarian",
                   "halal": "Halal", "gluten_free": "Gluten-free"}

# Plain-string template (placeholders filled with .replace) so CSS/JS braces need no escaping.
_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>World Cup 2026 Fan-Logistics Agent</title>
<style>
 :root{--bg:#eef1f4;--card:#fff;--ink:#1b2430;--muted:#5c6673;--line:#e3e7ec;
   --green:#0a7d4d;--green-d:#0b3d2e;--ring:rgba(10,125,77,.18);--err:#b42318}
 *{box-sizing:border-box}
 body{margin:0;background:var(--bg);color:var(--ink);line-height:1.55;
   font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
 .wrap{max-width:880px;margin:0 auto;padding:0 16px 56px}
 .hero{background:var(--green-d);color:#fff;border-radius:16px;padding:26px 26px;margin-top:24px}
 .hero h1{margin:0;font-size:1.6rem;letter-spacing:-.01em}
 .hero p{margin:8px 0 0;color:#bfe3d2;font-size:.96rem}
 .chips{margin-top:14px;display:flex;gap:8px;flex-wrap:wrap}
 .chip{background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.20);color:#eaf6ef;
   font-size:.76rem;padding:4px 11px;border-radius:999px}
 .card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:24px;
   box-shadow:0 1px 3px rgba(16,24,40,.06);margin-top:20px}
 .card h2{margin:0 0 4px;font-size:1.05rem}
 .hint{color:var(--muted);font-size:.9rem;margin:0 0 18px}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px 20px}
 .lbl{display:block;font-size:.74rem;font-weight:700;color:var(--muted);
   text-transform:uppercase;letter-spacing:.04em;margin-bottom:6px}
 select,input[type=time],input[type=number]{width:100%;padding:11px 12px;border:1px solid var(--line);
   border-radius:10px;font-size:1rem;background:#fff;color:var(--ink)}
 select:focus,input:focus{outline:none;border-color:var(--green);box-shadow:0 0 0 3px var(--ring)}
 .toggles{grid-column:1/-1;display:grid;grid-template-columns:1fr 1fr;gap:12px 20px;margin-top:2px}
 .chk{display:flex;align-items:center;gap:11px;padding:12px 14px;border:1px solid var(--line);
   border-radius:10px;cursor:pointer;font-weight:550;user-select:none}
 .chk:hover{border-color:#ccd4dc;background:#fafbfc}
 .chk input{width:18px;height:18px;accent-color:var(--green);cursor:pointer;margin:0}
 .go{grid-column:1/-1;margin-top:6px;background:var(--green);color:#fff;border:0;border-radius:11px;
   padding:14px 18px;font-size:1.04rem;font-weight:650;cursor:pointer;transition:background .15s}
 .go:hover{background:var(--green-d)}
 .go:disabled{opacity:.6;cursor:default}
 .status{display:flex;align-items:center;gap:9px;color:var(--muted);font-size:.9rem;margin-top:12px}
 .spin{width:15px;height:15px;border:2px solid var(--line);border-top-color:var(--green);
   border-radius:50%;animation:sp .8s linear infinite}
 @keyframes sp{to{transform:rotate(360deg)}}
 #result{display:none}
 #result.show{display:block}
 .md h2,.md h3,.md h4{color:var(--green-d);line-height:1.3}
 .md h2{font-size:1.2rem;margin:18px 0 8px}
 .md h3{font-size:1.05rem;margin:18px 0 7px}
 .md h4{font-size:.98rem;margin:14px 0 6px}
 .md h2:first-child,.md h3:first-child{margin-top:0}
 .md p{margin:9px 0}
 .md ul{margin:9px 0;padding-left:22px}
 .md li{margin:6px 0}
 .md strong{font-weight:680;color:var(--ink)}
 .md a{color:var(--green);text-decoration:underline}
 .md hr{border:0;border-top:1px solid var(--line);margin:16px 0}
 .errbox{color:var(--err);font-weight:550}
 .foot{color:var(--muted);font-size:.82rem;text-align:center;margin-top:26px}
 @media(max-width:640px){.grid,.toggles{grid-template-columns:1fr}.hero h1{font-size:1.35rem}}
</style></head><body>
<div class="wrap">
 <div class="hero">
  <h1>⚽ World Cup 2026 Fan-Logistics Agent</h1>
  <p>Tell me your match, and I'll plan the whole day — transit, food, budget, accessibility, and getting home.</p>
  <div class="chips"><span class="chip">Gemini 3.1</span><span class="chip">Google ADK</span>
   <span class="chip">Traced in Arize Phoenix</span><span class="chip">Self-improving evals</span></div>
 </div>

 <div class="card">
  <h2>Plan your match day</h2>
  <p class="hint">Fill in a few details and get a complete, constraint-aware plan in ~20–40 seconds.</p>
  <form id="f" class="grid" onsubmit="return go(event)">
   <div><span class="lbl">Venue</span><select name="venue">__VENUE_OPTS__</select></div>
   <div><span class="lbl">Kickoff time</span><input type="time" name="kickoff" value="16:00"></div>
   <div><span class="lbl">Budget per person ($)</span><input type="number" name="budget" value="60" min="1"></div>
   <div><span class="lbl">Dietary preference</span><select name="dietary">__DIET_OPTS__</select></div>
   <div class="toggles">
    <label class="chk"><input type="checkbox" name="is_knockout"> Knockout game?</label>
    <label class="chk"><input type="checkbox" name="tickets_paid" checked> Tickets already paid?</label>
    <label class="chk"><input type="checkbox" name="accessibility_needs"> Accessibility needs?</label>
    <label class="chk"><input type="checkbox" name="want_post_game_stop"> Post-game food / dessert stop?</label>
   </div>
   <button class="go" type="submit">Plan my match day</button>
  </form>
  <div id="status" class="status" style="display:none"><span class="spin"></span>
   <span>Planning your match day… (~20–40s)</span></div>
 </div>

 <div id="result" class="card"><div id="out" class="md"></div></div>

 <p class="foot">Open-hours come from live Google Search grounding; travel &amp; egress times are
  estimates from comparable past events, not live match-day traffic.</p>
</div>
<script>
function esc(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}
function inl(s){
  s=esc(s);
  s=s.replace(/\\[([^\\]]+)\\]\\((https?:\\/\\/[^\\s)]+)\\)/g,'<a href="$2" target="_blank" rel="noopener">$1</a>');
  s=s.replace(/\\*\\*([^*]+)\\*\\*/g,'<strong>$1</strong>');
  s=s.replace(/(^|[^*])\\*([^*\\n]+)\\*/g,'$1<em>$2</em>');
  return s;
}
function md(t){
  const lines=t.replace(/\\r/g,'').split('\\n');
  let h='',inList=false;
  const close=()=>{if(inList){h+='</ul>';inList=false;}};
  for(let raw of lines){
    const line=raw.replace(/\\s+$/,'');
    if(!line.trim()){close();continue;}
    let m;
    if(m=line.match(/^\\s*(#{1,6})\\s+(.*)$/)){close();let l=Math.min(m[1].length+1,4);h+='<h'+l+'>'+inl(m[2])+'</h'+l+'>';continue;}
    if(/^\\s*([-*])\\s+/.test(line)){if(!inList){h+='<ul>';inList=true;}h+='<li>'+inl(line.replace(/^\\s*[-*]\\s+/,''))+'</li>';continue;}
    if(/^\\s*-{3,}\\s*$/.test(line)){close();h+='<hr>';continue;}
    close();h+='<p>'+inl(line)+'</p>';
  }
  close();return h;
}
async function go(ev){
  ev.preventDefault();
  const f=document.getElementById('f'), btn=f.querySelector('.go');
  const st=document.getElementById('status'), res=document.getElementById('result'), out=document.getElementById('out');
  const body={
    venue:f.venue.value, kickoff:f.kickoff.value, budget:parseInt(f.budget.value||'0',10),
    dietary:f.dietary.value, is_knockout:f.is_knockout.checked, tickets_paid:f.tickets_paid.checked,
    accessibility_needs:f.accessibility_needs.checked, want_post_game_stop:f.want_post_game_stop.checked
  };
  btn.disabled=true; st.style.display='flex'; res.classList.remove('show'); out.innerHTML='';
  try{
    const r=await fetch('/plan-form',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const j=await r.json();
    if(j.plan){out.className='md';out.innerHTML=md(j.plan);}
    else{out.className='errbox';out.textContent=j.error||JSON.stringify(j);}
    res.classList.add('show');
  }catch(e){out.className='errbox';out.textContent='Request failed: '+e;res.classList.add('show');}
  btn.disabled=false; st.style.display='none';
  res.scrollIntoView({behavior:'smooth',block:'nearest'});
  return false;
}
</script>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    venue_opts = "".join(f"<option value='{v}'>{v}</option>" for v in KNOWN_VENUES)
    diet_opts = "".join(f"<option value='{k}'>{_DIETARY_LABELS[k]}</option>"
                        for k in _DIETARY_CHOICES)
    return _PAGE.replace("__VENUE_OPTS__", venue_opts).replace("__DIET_OPTS__", diet_opts)
