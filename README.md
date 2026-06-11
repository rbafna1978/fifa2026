# ⚽ World Cup 2026 Fan-Logistics Agent

**A Gemini 3.1 agent that plans your World Cup 2026 match day — and improves itself by reading its own Arize Phoenix eval scores.**

🌐 **Live demo (hosted on Cloud Run):** https://worldcup-agent-324051541372.us-central1.run.app
🏷️ Submission for the **Google Cloud "Rapid Agent" Hackathon — Arize track**.

Open the URL, fill in a short form (venue, kickoff, budget, plus toggles for knockout / tickets-paid / accessibility / dietary / post-game stop), and get a complete, constraint-aware plan in ~20–40s. Every run is traced to Phoenix.

---

## What it does

A fan-logistics planner for World Cup 2026 host venues. Given a venue, kickoff time, and per-person budget, it produces a complete match-day plan as a multi-step tool chain:

1. **`get_match_logistics`** → city, public-transit route, recommended gate-arrival buffer, a post-event **egress estimate**, and **sourced accessibility** details (parking / entrances / transit drop-off / companion seating).
2. **`find_food_near`** → curated food options within a share of the budget, with an optional **dietary filter** (vegan / vegetarian / halal / gluten-free). If nothing matches, it says so honestly rather than inventing a place.
3. **`estimate_match_end`** → pure-arithmetic earliest/latest match end time (normal time ~+113 min; a **knockout** game adds an extra-time + penalties tail → latest ~+170 min).
4. **`build_day_plan`** → assembles the timeline, gate-arrival time (kickoff − buffer), and per-person cost breakdown — honoring **tickets-already-paid** (budget then covers transit + food + any post-game stop; tickets are never priced).
5. **`live_search`** → keyless Google Search grounding for current facts (fixtures, kickoff times, advisories) **and** a post-game stop's opening hours, so the plan can check it'll still be open given the estimated match end.

It honors flags the user sets: **is_knockout, dietary, tickets_paid, accessibility_needs, want_post_game_stop**. Travel/egress times are clearly labelled as **estimates from comparable past events, not live match-day traffic**; open-hours come from live search.

Curated venues: MetLife, SoFi, AT&T, Mercedes-Benz, Lumen Field. Accessibility data is real and sourced from each venue's official accessibility page (source URLs in `tools.py`).

---

## The Arize-track story (the differentiator)

This project is built around **meaningful Phoenix tracing, MCP self-introspection, and a verified self-improvement loop.**

### 1. Fully traced in Phoenix via OpenInference
Tracing is registered once (`agent/instrumentation.py`, `phoenix.otel.register(..., auto_instrument=True)`). Every LLM call, tool call, and agent step — locally **and** from the deployed Cloud Run instance — appears as spans in the Phoenix project `worldcup-agent`.

### 2. Self-introspection over the Phoenix MCP server
A `reflection` sub-agent holds the **`@arizeai/phoenix-mcp`** toolset (over stdio). It lets the agent read its **own** past Phoenix runs — which tools it called, latencies, statuses, and eval scores — and answer questions about them. The raw MCP trace tools return whole-span payloads that overflow the model context, so `worldcup_agent/phoenix_reflection.py` wraps the toolset to: expose only the verified, bounded summary tools (correct `tool_filter`), clamp the page `limit`, and prune heavy span bodies down to summary fields.

### 3. A verified self-improvement loop
The agent scores and learns from its own plans:

- **LLM-as-judge** (`agent/eval.py`): Gemini 3.1 scores each plan 0–1 on four concrete, checkable criteria — (a) total per-person cost ≤ budget, (b) gate time = kickoff − the venue's buffer, (c) transit names a real option from the logistics tool, (d) plan is complete. The judge returns structured per-criterion booleans + a rationale; the numeric score is computed in code, not by the LLM.
- **Score logged back to Phoenix** as a `plan_quality` **span annotation** on the run's root span (`spans.add_span_annotation`) — visible in the Phoenix UI and readable back via `get-span-annotations`.
- **The agent reads its own scores and corrects itself.** A `read_eval_history` tool reads recent `plan_quality` scores **and rationales** from Phoenix. The planner reads that history, identifies the recurring weaknesses *from the rationales*, and fixes them in the next plan. Nothing about the fix is hardcoded.

**Concrete before/after** (`make demo-loop`, deterministic across runs):

| Run | Mode | Score | Why |
| --- | --- | --- | --- |
| 1 | naive (no reflection) | **0.50** | wrong gate time (used 60-min buffer, not the venue's 90), generic transit |
| 2 | naive (no reflection) | **0.50** | same recurring weaknesses |
| 3 | reflect (reads its own evals) | **1.00** | reads the rationales, then fixes the gate math and names the real transit line |

> Design note: the live loop reads eval history via a **direct Phoenix read** (`read_eval_history`), which is fast and reliable. The **MCP `reflection`** path is kept for the standalone introspection demo. On Cloud Run (a Python-only container with no `npx`), the `reflection` tool is omitted automatically and the loop still works via the direct read.

---

## Architecture

```
root_agent  (worldcup_agent/agent.py — Gemini 3.1, Google ADK)
│
├─ get_match_logistics   FunctionTool   venue logistics + egress + sourced accessibility (tools.py)
├─ find_food_near        FunctionTool   curated food options + dietary filter           (tools.py)
├─ estimate_match_end    FunctionTool   earliest/latest end time (knockout aware)        (tools.py)
├─ build_day_plan        FunctionTool   assembles the plan (tickets_paid, post_game_cost)(tools.py)
├─ read_eval_history     FunctionTool   reads own plan_quality scores from Phoenix       (eval.py)
├─ live_search           AgentTool  →  sub-agent w/ built-in google_search (keyless grounding)
└─ reflection            AgentTool  →  sub-agent w/ Phoenix MCP toolset    (local only; phoenix_reflection.py)

eval.py            LLM-as-judge + writes plan_quality span annotations to Phoenix
run_eval.py        runs a planning turn → judges it → logs the score (naive | reflect | demo)
instrumentation.py phoenix.otel.register(auto_instrument=True)
server.py          FastAPI serving layer for Cloud Run: structured form UI, /plan-form, /plan, /status
main.py            one-shot CLI turn
```

### Web UI
The hosted page (`server.py`) is a clean, responsive **structured form** — venue dropdown, kickoff time, budget, dietary dropdown, and knockout / tickets-paid / accessibility / post-game toggles. On submit it POSTs to **`/plan-form`**, which composes the fields **server-side** into the natural-language request the agent already expects (so the clean composed input is what gets traced) and runs the same traced turn. The plan is rendered from markdown to formatted HTML in the browser. `/plan` (raw `{"message": ...}` in → traced plan out) remains available unchanged.

---

## Run it locally

**Prerequisites:** Python 3.11, [uv](https://docs.astral.sh/uv/), Google ADC (`gcloud auth application-default login`) with Vertex access, a Phoenix Cloud key, and Node.js (for the MCP `reflection` path).

```bash
uv sync
cp .env.example .env      # then fill in real values — see .env.example for the keys
```

Required env vars (names and placeholders in [`.env.example`](.env.example) — never commit real values):
`GOOGLE_GENAI_USE_VERTEXAI`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`,
`GEMINI_MODEL=gemini-3.1-pro-preview`, `PHOENIX_API_KEY`, `PHOENIX_COLLECTOR_ENDPOINT`, `PHOENIX_PROJECT_NAME`.

### Key make targets

```bash
make demo-loop      # the headline: two weak plans (0.50) → agent reads its evals → 1.00, with a before/after summary
make eval-naive     # a single "before" run: plan without reflection → low score, logged to Phoenix
make eval-reflect   # a single "after" run: agent reads its own eval history, then plans → high score

make run MESSAGE='Plan my match day at SoFi Stadium, kickoff 16:00, budget 60 dollars per person.'
make run MESSAGE='Use reflection to inspect your own recent Phoenix runs and plan_quality scores.'   # MCP self-introspection
```

(Use single quotes for `MESSAGE`, and avoid a literal `$` in the message — it breaks the shell.) Traces appear in the Phoenix project `worldcup-agent`.

### Serve the web UI locally

```bash
cd agent && uv run uvicorn server:app --host 127.0.0.1 --port 8080
# open http://127.0.0.1:8080 for the form  ·  GET /status for config
# POST /plan-form {"venue","kickoff","budget","is_knockout","tickets_paid","dietary","accessibility_needs","want_post_game_stop"}
# POST /plan      {"message": "..."}   (raw free-text path, unchanged)
```

---

## Future work

Deliberate scope lines, called out honestly:

- **Live traffic / crowd-queue modeling.** Transit times, gate buffers, and post-event
  egress are curated/historical estimates (from comparable past NFL games and concerts at
  each venue), clearly labelled as such everywhere they surface. Swapping in a live
  traffic/transit API for match day is future work.
- **Constraint-aware eval criteria.** The LLM-as-judge currently scores the original four
  criteria (budget, gate time, real transit, completeness) — kept stable on purpose to
  protect the verified `make demo-loop` 0.50 → 1.00 result. Adding criteria for the newer
  constraints (dietary honesty, accessibility sourcing, knockout envelope, post-game
  feasibility) is noted as future work.
- **MCP reflection on Cloud Run.** The `reflection` sub-agent (Phoenix MCP over `npx`)
  needs Node, so it runs locally but is omitted from the Python-only Cloud Run container.
  The hosted self-improvement loop uses the direct `read_eval_history` Phoenix read
  instead, which works the same everywhere. Running MCP reflection on the hosted instance
  (e.g. via a Node-enabled image or a hosted MCP transport) is future work.
- **More venues / fixtures.** Five curated venues today; broader venue coverage and live
  fixture lookups (beyond the current `live_search` grounding) would extend the demo to
  the full 2026 schedule.

## Tech stack

- **Gemini 3.1** (`gemini-3.1-pro-preview`, Vertex AI, global endpoint) — model and LLM-as-judge.
- **Google ADK** (`google-adk`) — agent runtime, tools, sub-agents.
- **Arize Phoenix** + **OpenInference** — tracing, span annotations, and the `@arizeai/phoenix-mcp` server for self-introspection.
- **FastAPI + uvicorn** — serving layer; **Cloud Run** (scale-to-zero) + **Secret Manager** for the hosted deployment.
- **uv** — dependency management. **No paid API keys** — web grounding uses ADK's built-in keyless `google_search`; Phoenix is the free tier.

## License

Apache-2.0 — see [LICENSE](LICENSE).
