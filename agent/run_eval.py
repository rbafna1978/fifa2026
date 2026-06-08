"""Run the planner, evaluate the plan, and log the score to Phoenix (the loop).

Usage:
    uv run python run_eval.py naive     # weak plan (ignores venue specifics)
    uv run python run_eval.py reflect   # reads its own eval scores first, then improves

Both modes plan the SAME fixed scenario (SoFi Stadium, 16:00 kickoff, $60/person)
so the before/after is deterministic and demoable. Each run:
  1. executes a planning turn inside a single root span (so the whole run is one trace),
  2. judges the plan with the Gemini-3.1 LLM-as-judge (eval.py),
  3. writes a `plan_quality` annotation onto that root span in Phoenix,
  4. prints the plan, the score, and confirms the annotation was written + read back.
"""
from __future__ import annotations

import asyncio
import secrets
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from opentelemetry import trace
from openinference.semconv.trace import SpanAttributes, OpenInferenceSpanKindValues

from google.adk.runners import InMemoryRunner
from google.genai import types

from instrumentation import setup_tracing
from worldcup_agent.agent import root_agent
from worldcup_agent.tools import get_match_logistics
from eval import evaluate_plan, log_eval_to_phoenix, wait_for_span, read_plan_quality

# Fixed demo scenario.
VENUE = "SoFi Stadium"
KICKOFF = "16:00"
BUDGET = 60

_BASE = (f"Plan my match day at {VENUE}. Kickoff is {KICKOFF}. My budget is "
         f"${BUDGET} per person total. Give a timeline (when to leave, transit, "
         f"where to eat with cost, and gate-arrival time), plus a per-person cost breakdown.")

# NAIVE mode: deliberately induces the recurring weaknesses (wrong gate buffer +
# generic transit) so the eval score is low and the rationale is concrete.
NAIVE = (_BASE + " Keep it quick: do NOT look up venue-specific logistics. Just assume a "
         "standard 60-minute gate buffer and describe transit generically as 'public transit'.")

# REFLECT mode: the improvement is agent-driven. It must read its own eval history and
# let the rationales tell it what to fix — nothing about the specific fix is hardcoded here.
REFLECT = (_BASE + " Before you plan, call read_eval_history to review how your recent "
           "plans scored and the explanations of what went wrong. Identify the recurring "
           "weaknesses and make sure THIS plan corrects them. Use your logistics tools to "
           "get exact, correct values.")

MODES = {"naive": NAIVE, "reflect": REFLECT}


async def _run_planner(message: str) -> tuple[str, str, str]:
    """Run one planning turn inside a root span. Returns (plan_text, trace_id, span_id)."""
    setup_tracing()
    tracer = trace.get_tracer("worldcup.eval")
    app_name, user_id, session_id = "worldcup_eval", "local_user", secrets.token_hex(8)
    runner = InMemoryRunner(agent=root_agent, app_name=app_name)
    await runner.session_service.create_session(
        app_name=app_name, user_id=user_id, session_id=session_id)

    chunks: list[str] = []
    t0 = time.monotonic()
    with tracer.start_as_current_span("match_day_plan") as span:
        span.set_attribute(SpanAttributes.OPENINFERENCE_SPAN_KIND,
                           OpenInferenceSpanKindValues.CHAIN.value)
        span.set_attribute(SpanAttributes.INPUT_VALUE, message)
        ctx = span.get_span_context()
        trace_id = format(ctx.trace_id, "032x")
        span_id = format(ctx.span_id, "016x")
        async for event in runner.run_async(
            user_id=user_id, session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=message)]),
        ):
            # Live progress trace (to stderr): every tool call / response, with timing.
            for part in (event.content.parts if event.content and event.content.parts else []):
                fc = getattr(part, "function_call", None)
                fr = getattr(part, "function_response", None)
                dt = time.monotonic() - t0
                if fc:
                    print(f"  [{dt:6.1f}s] -> call {fc.name}({dict(fc.args or {})})",
                          file=sys.stderr, flush=True)
                elif fr:
                    print(f"  [{dt:6.1f}s] <- {fr.name} returned", file=sys.stderr, flush=True)
                elif getattr(part, "text", None):
                    chunks.append(part.text)
        plan_text = "".join(chunks).strip()
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, plan_text)
    return plan_text, trace_id, span_id


async def main(mode: str):
    message = MODES[mode]
    plan_text, trace_id, span_id = await _run_planner(message)

    print("\n" + "=" * 72)
    print(f"MODE: {mode}   (trace {trace_id}  root span {span_id})")
    print("=" * 72)
    print("PLAN:\n" + plan_text + "\n")

    ground_truth = get_match_logistics(VENUE)
    result = evaluate_plan(plan_text, VENUE, KICKOFF, BUDGET, ground_truth)
    print(f"EVAL score={result.score:.2f}  label={result.label}")
    print(f"  criteria: {result.criteria}")
    print(f"  rationale: {result.rationale}")

    print("Waiting for trace to flush to Phoenix...")
    if not wait_for_span(span_id, trace_id):
        print("  WARNING: root span not visible in Phoenix yet; annotation may lag.")
    ann_id = log_eval_to_phoenix(span_id, result)
    print(f"  wrote plan_quality annotation: id={ann_id}")

    back = read_plan_quality([span_id])
    for a in back:
        r = a.get("result", {})
        print(f"  read back -> name={a.get('name')} score={r.get('score')} "
              f"label={r.get('label')}")
    print("=" * 72 + "\n")
    return result


async def demo() -> None:
    """Repeatable before/after: two weak plans, then the agent reads its own
    evals and produces a better one. Prints a final BEFORE/AFTER summary."""
    scores = []
    for mode in ("naive", "naive", "reflect"):
        result = await main(mode)
        scores.append((mode, result.score, result.label))
    print("#" * 72)
    print("# SELF-IMPROVEMENT LOOP — BEFORE / AFTER")
    print("#" * 72)
    for i, (mode, score, label) in enumerate(scores, 1):
        tag = "BEFORE" if mode == "naive" else "AFTER "
        print(f"#  {tag} run {i} [{mode:7}] -> score {score:.2f}  ({label})")
    before = max(s for m, s, _ in scores if m == "naive")
    after = [s for m, s, _ in scores if m == "reflect"][0]
    print(f"#  improvement: {before:.2f} -> {after:.2f}  "
          f"(+{after - before:.2f}) by reading its own eval history")
    print("#" * 72)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "naive"
    if mode not in MODES and mode != "demo":
        print(f"usage: run_eval.py [{'|'.join(MODES)}|demo]")
        sys.exit(1)
    try:
        asyncio.run(demo() if mode == "demo" else main(mode))
    except (RuntimeError, asyncio.CancelledError):
        # Harmless MCP stdio teardown race on one-shot exit (see main.py).
        pass
