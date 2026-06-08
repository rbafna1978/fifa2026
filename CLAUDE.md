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

## Status — Step 4 DONE (eval / self-improvement loop, the finale)
- **LLM-as-judge** (`agent/eval.py`): `evaluate_plan()` scores a plan 0..1 on 4 checkable
  criteria — (a) total per-person cost <= budget, (b) gate time = kickoff - venue buffer,
  (c) transit names a real option from `get_match_logistics`, (d) plan complete. Judge is
  Gemini 3.1 with a structured `JudgeVerdict` (per-criterion bools + rationale); the numeric
  score is computed in code (mean of bools), not by the LLM. Verified: weak plan -> 0.50,
  strong plan -> 1.00.
- **Score logged to Phoenix** as a `plan_quality` span annotation on the run's ROOT span
  (`eval.log_eval_to_phoenix`, via `phoenix.client` `spans.add_span_annotation`). Visible in
  the UI and readable via `get-span-annotations`. `run_eval.py` wraps each planning turn in
  one `match_day_plan` root span (openinference CHAIN) so the whole run is one annotated trace.
- **Loop closed, agent-driven:** the planner has a `read_eval_history` FunctionTool
  (`eval.read_eval_history`) that reads its own recent `plan_quality` scores + rationales
  directly from Phoenix (~2-3s). In `reflect` mode it reads that history, names the recurring
  weaknesses FROM the rationales, and fixes them -> 0.50 -> 1.00, deterministically across 3+ runs.
  - DESIGN NOTE: the live improvement loop intentionally uses this direct read, NOT the MCP
    `reflection` sub-agent. The MCP path (agent-in-an-agent hitting remote Phoenix) ran ~100s
    and intermittently 404'd — too slow/flaky to drive the loop. The MCP `reflection` tool is
    KEPT for the standalone self-introspection demo (it reads the same annotations over MCP and
    works fine, ~40-70s). So judges get both: robust self-improvement + meaningful MCP use.
- **Before/after demo (for the video):** `make demo-loop` runs naive, naive, reflect and prints
  a BEFORE/AFTER summary (0.50, 0.50 -> 1.00). Also `make eval-naive` / `make eval-reflect`.
  Live tool-call trace prints to stderr. MCP timeout lowered to 25s in `agent.py` so a slow
  reflection call fails fast instead of hanging.

## Status — LEFT TO BUILD
- **Deploy to Cloud Run** for the required hosted project URL (free tier; keep within credits).
- **~3 minute demo video** showing: multi-step plan, live search, self-introspection, self-improvement.
- **Devpost submission**: hosted URL + public repo URL + video + select Arize track + form.

## Conventions
- Keep edits minimal and test after each change with `make run`.
- Don't introduce paid dependencies or change the model away from Gemini 3.1.
- Commit with clear messages; never stage `.env`.
