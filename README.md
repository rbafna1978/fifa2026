# ⚽ World Cup 2026 Fan-Logistics Agent

**A Gemini 3.1 agent that plans your World Cup 2026 match day — and improves itself by reading its own Arize Phoenix eval scores.**

🌐 **Live demo (hosted on Cloud Run):** https://worldcup-agent-324051541372.us-central1.run.app
🏷️ Submission for the **Google Cloud "Rapid Agent" Hackathon — Arize track**.

Open the URL, type a request (e.g. *"Plan my match day at SoFi Stadium, kickoff 16:00, budget $60 per person"*), and get a complete plan in ~15–30s. Every run is traced to Phoenix.

---

## What it does

A fan-logistics planner for World Cup 2026 host venues. Given a venue, kickoff time, and per-person budget, it produces a complete match-day plan as a multi-step tool chain:

1. **`get_match_logistics`** → city, public-transit route, recommended gate-arrival buffer.
2. **`find_food_near`** → curated food options within a share of the budget.
3. **`build_day_plan`** → assembles the timeline, gate-arrival time (kickoff − buffer), and per-person cost breakdown.
4. **`live_search`** → keyless Google Search grounding for current facts (fixtures, kickoff times, advisories).

Curated venues: MetLife, SoFi, AT&T, Mercedes-Benz, Lumen Field.

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
├─ get_match_logistics   FunctionTool   curated venue logistics  (tools.py)
├─ find_food_near        FunctionTool   curated food options     (tools.py)
├─ build_day_plan        FunctionTool   assembles the plan       (tools.py)
├─ read_eval_history     FunctionTool   reads own plan_quality scores from Phoenix (eval.py)
├─ live_search           AgentTool  →  sub-agent w/ built-in google_search (keyless grounding)
└─ reflection            AgentTool  →  sub-agent w/ Phoenix MCP toolset    (local only; phoenix_reflection.py)

eval.py            LLM-as-judge + writes plan_quality span annotations to Phoenix
run_eval.py        runs a planning turn → judges it → logs the score (naive | reflect | demo)
instrumentation.py phoenix.otel.register(auto_instrument=True)
server.py          FastAPI serving layer for Cloud Run (single-page UI + /plan + /status)
main.py            one-shot CLI turn
```

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
# open http://127.0.0.1:8080  ·  GET /status for config  ·  POST /plan {"message": "..."}
```

---

## Tech stack

- **Gemini 3.1** (`gemini-3.1-pro-preview`, Vertex AI, global endpoint) — model and LLM-as-judge.
- **Google ADK** (`google-adk`) — agent runtime, tools, sub-agents.
- **Arize Phoenix** + **OpenInference** — tracing, span annotations, and the `@arizeai/phoenix-mcp` server for self-introspection.
- **FastAPI + uvicorn** — serving layer; **Cloud Run** (scale-to-zero) + **Secret Manager** for the hosted deployment.
- **uv** — dependency management. **No paid API keys** — web grounding uses ADK's built-in keyless `google_search`; Phoenix is the free tier.

## License

Apache-2.0 — see [LICENSE](LICENSE).
