# CLAUDE.md — World Cup 2026 Fan-Logistics Agent

Context for Claude Code working on this repo. Read this fully before changing code.

## What this is
A submission for the **Google Cloud "Rapid Agent" Hackathon — Arize track**
(Devpost). Deadline: **June 11, 2026, 2:00 PM PDT**. Goal: a Gemini agent, built
on Google ADK, that is fully traced in **Arize Phoenix** and can **introspect its
own traces via the Phoenix MCP server** — a self-improvement loop. The agent's
real-world task: plan a World Cup 2026 match day (transit + food + budget) for a fan.

## What the Arize judges score (optimize for these)
1. Technological implementation (quality use of Google Cloud + Phoenix/MCP).
2. Design / UX.
3. Potential impact.
4. Quality/originality of the idea.
Their stated differentiator: **meaningful tracing + MCP use, and the quality of the
agent's self-improvement loop.** Depth of correct Phoenix usage matters most.

## Hard constraints (do not violate)
- Model MUST be Gemini 3: use `gemini-3.1-pro-preview` (the bare `gemini-3-pro-preview`
  was retired). It is **global-endpoint only** on Vertex — `.env` sets
  `GOOGLE_CLOUD_LOCATION=global`. Needs `google-genai >= 1.51` (have 1.74).
- **No paid API keys.** Web data uses ADK's built-in `google_search` grounding
  (keyless, via Vertex auth). Phoenix Cloud free tier. Do not add anything that
  requires a paid key.
- Runtime must be code-owned (ADK) — the visual Agent Builder is NOT allowed on this track.
- Repo is public; **never commit `.env`** (it holds the Phoenix key). `.env` is gitignored.

## Architecture
Root planner agent (`worldcup_agent/agent.py`, exposes `root_agent`) with tools:
- 3 curated `FunctionTool`s in `worldcup_agent/tools.py`:
  `get_match_logistics`, `find_food_near`, `build_day_plan`.
- `live_search`: a sub-agent holding the built-in `google_search`, exposed via
  `AgentTool`. (Built-in tools can't share an agent with function tools — hence the wrapper.)
- `reflection`: a sub-agent holding the Phoenix MCP toolset (`@arizeai/phoenix-mcp`
  over stdio via npx), exposed via `AgentTool`. Lets the agent read its own Phoenix runs.
Prompts: `worldcup_agent/prompt.py` (planner), `worldcup_agent/reflection_prompt.py` (reflection).
Tracing: `agent/instrumentation.py` (`setup_tracing()`), called at import in `agent.py`.
Entry point: `agent/main.py` (one-shot CLI turn via `InMemoryRunner`).

## Environment / how to run
- Package manager is **uv**. Python 3.11.
- Secrets/config live in `.env` at repo root (NOT `.env.example`). Required keys:
  `GOOGLE_GENAI_USE_VERTEXAI=1`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=global`,
  `GEMINI_MODEL=gemini-3.1-pro-preview`, `PHOENIX_API_KEY` (px_live_...),
  `PHOENIX_COLLECTOR_ENDPOINT=https://app.phoenix.arize.com/s/fifa2026`,
  `PHOENIX_PROJECT_NAME=worldcup-agent`.
- Google auth is via ADC (`gcloud auth application-default login`), already set up.
- Node.js installed (Phoenix MCP runs through `npx`).
- Run a turn: `make run MESSAGE='...'`  (use SINGLE quotes; `$` in the message breaks the shell).
- Verify tracing: traces appear in Phoenix Cloud project `worldcup-agent`. You can't see
  the Phoenix web UI from here, but you CAN verify by reading stdout and by asking the
  agent a reflection question (it reads its own traces via MCP).

## Status — DONE
- Day 0: starter cloned, Gemini 3.1 + Phoenix tracing working, own public repo w/ Apache-2.0.
- Step 1: curated multi-tool chain (logistics -> food -> plan), traced. Confirmed in Phoenix.
- Step 2: keyless Google Search grounding via `live_search` AgentTool. Pulled real SoFi fixtures.
- Step 3 (mostly): `reflection` agent with Phoenix MCP. The agent HAS successfully read and
  reasoned about its own past traces at least once.

## Status — CURRENT BLOCKER (fix this first)
The `reflection` path is unstable. Two distinct failures seen:
1. **400 INVALID_ARGUMENT "input token count exceeds 1048576"** — the Phoenix MCP
   list/get-traces tools return huge full-span payloads (entire LLM input/output bodies),
   which overflow the model context when fed back as a tool result.
2. A `tool_filter=[...]` attempt used **guessed tool names that don't exist**, so the
   reflection agent got an empty toolset and reported it "lacks the necessary tools."
**Fix direction:** (a) get the REAL Phoenix MCP tool names (run the server / ask the agent
to enumerate them) and apply a correct `tool_filter` to expose only lightweight
listing/summary tools; (b) keep `reflection_prompt.py` constraints (only 3-5 most recent
traces, summary fields only, never full span bodies); (c) consider post-processing/truncating
MCP results before they reach the model. Goal: stable reflection answer, no 400, across 3+ runs.
Note: the `Attempted to exit cancel scope...` error on shutdown is a HARMLESS stdio-teardown
race in one-shot mode — `main.py` swallows it in a try/except; ignore it.

## Status — LEFT TO BUILD
- **Step 4 — eval / self-improvement loop (the finale, highest value):** score each plan
  (budget respected? gate buffer correct? transit plausible?) via an LLM-as-judge, log the
  score to Phoenix, and have the agent read its own eval scores via the reflection path and
  improve the next plan. Show the score going up.
- **Deploy to Cloud Run** for the required hosted project URL (free tier; keep within credits).
- **~3 minute demo video** showing: multi-step plan, live search, self-introspection, self-improvement.
- **Devpost submission**: hosted URL + public repo URL + video + select Arize track + form.

## Conventions
- Keep edits minimal and test after each change with `make run`.
- Don't introduce paid dependencies or change the model away from Gemini 3.1.
- Commit with clear messages; never stage `.env`.
