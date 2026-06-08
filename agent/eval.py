"""LLM-as-judge evaluator for World Cup match-day plans + Phoenix score logging.

Step 4 of the hackathon build: the self-improvement loop. After the planner
produces a match-day plan we score it 0..1 on four concrete, checkable criteria
using Gemini 3.1 as the judge, then write the score back to Phoenix as a span
annotation on the run's ROOT span. That annotation is visible in the Phoenix UI
and readable through the existing reflection path (`get-span-annotations`), which
is how the agent later reads its own scores and improves.

No paid keys: the judge runs on Vertex (the same `gemini-3.1-pro-preview` /
global-endpoint config the agent uses) and Phoenix is the free hosted tier.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone

from google import genai
from google.genai import types
from pydantic import BaseModel

# The annotation name everything keys off of — written here, read back by the
# reflection agent and the demo verifier.
ANNOTATION_NAME = "plan_quality"
PASS_THRESHOLD = 0.75
_JUDGE_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-pro-preview")


class JudgeVerdict(BaseModel):
    """Structured output the Gemini judge must return."""

    cost_within_budget: bool
    gate_time_correct: bool
    transit_is_real_named_option: bool
    plan_complete: bool
    rationale: str


@dataclass
class EvalResult:
    score: float                 # 0..1, fraction of criteria passed
    label: str                   # "pass" | "needs_improvement"
    rationale: str               # one-line judge explanation
    criteria: dict[str, bool]    # per-criterion pass/fail

    def as_dict(self) -> dict:
        return asdict(self)


def _gate_time(kickoff: str, buffer_min: int) -> str:
    """Correct gate-arrival time = kickoff - buffer, as HH:MM."""
    t = datetime.strptime(kickoff, "%H:%M")
    return (t - timedelta(minutes=buffer_min)).strftime("%H:%M")


_JUDGE_SYSTEM = (
    "You are a strict evaluator of World Cup match-day plans. You are given the "
    "user's request, the ground-truth logistics for the venue, and the plan the "
    "agent produced. Judge ONLY against the provided ground truth. Be literal and "
    "deterministic: a criterion is true only if the plan clearly satisfies it."
)


def _judge_prompt(plan_text, venue, kickoff, budget, ground_truth) -> str:
    buffer_min = ground_truth.get("gate_buffer_min")
    correct_gate = _gate_time(kickoff, buffer_min)
    return f"""USER REQUEST
- Venue: {venue}
- Kickoff: {kickoff}
- Budget (per person, total): ${budget}

GROUND TRUTH (authoritative)
- City: {ground_truth.get('city')}
- Recommended gate-arrival buffer: {buffer_min} minutes
- Correct gate-arrival time (kickoff minus buffer): {correct_gate}
- Real transit options for this venue: {ground_truth.get('transit')}

PLAN TO EVALUATE
\"\"\"
{plan_text}
\"\"\"

Score each criterion as true/false:
1. cost_within_budget: the plan's total per-person cost is <= ${budget}.
2. gate_time_correct: the plan's stated gate/arrival time equals {correct_gate} (allow +/- 5 min).
   If the plan uses a different buffer than {buffer_min} min, this is FALSE.
3. transit_is_real_named_option: the plan's transit references a specific named option that
   actually appears in the real transit options above (e.g. a named line, train, or bus).
   Generic phrasing like "take public transit" or a made-up option is FALSE.
4. plan_complete: the plan includes all of transit, food, a timeline, and a cost breakdown.

Then give a single-sentence rationale naming the most important failure (or confirming success)."""


def evaluate_plan(plan_text: str, venue: str, kickoff: str, budget: int,
                  ground_truth: dict) -> EvalResult:
    """Run the Gemini-3.1 judge and return a structured, deterministic score."""
    client = genai.Client()  # reads GOOGLE_GENAI_USE_VERTEXAI / project / location from env
    resp = client.models.generate_content(
        model=_JUDGE_MODEL,
        contents=_judge_prompt(plan_text, venue, kickoff, budget, ground_truth),
        config=types.GenerateContentConfig(
            system_instruction=_JUDGE_SYSTEM,
            temperature=0.0,
            response_mime_type="application/json",
            response_schema=JudgeVerdict,
        ),
    )
    verdict: JudgeVerdict = resp.parsed
    criteria = {
        "cost_within_budget": verdict.cost_within_budget,
        "gate_time_correct": verdict.gate_time_correct,
        "transit_is_real_named_option": verdict.transit_is_real_named_option,
        "plan_complete": verdict.plan_complete,
    }
    score = sum(criteria.values()) / len(criteria)  # computed in code, not by the LLM
    label = "pass" if score >= PASS_THRESHOLD else "needs_improvement"
    return EvalResult(score=score, label=label, rationale=verdict.rationale.strip(),
                      criteria=criteria)


# --- Phoenix annotation I/O -------------------------------------------------

def _phoenix_client():
    from phoenix.client import Client
    return Client(
        base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
        api_key=os.environ["PHOENIX_API_KEY"],
    )


def _project() -> str:
    return os.environ.get("PHOENIX_PROJECT_NAME", "worldcup-agent")


def wait_for_span(span_id: str, trace_id: str, attempts: int = 12, delay: float = 2.5) -> bool:
    """Poll Phoenix until the just-emitted root span is queryable (traces flush async)."""
    import time
    client = _phoenix_client()
    for _ in range(attempts):
        try:
            spans = client.spans.get_spans(
                project_identifier=_project(), trace_ids=[trace_id], limit=50)
            if any(s.get("context", {}).get("span_id") == span_id for s in spans):
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def log_eval_to_phoenix(span_id: str, result: EvalResult) -> str:
    """Write the eval as a `plan_quality` annotation on the run's root span.

    Returns the inserted annotation id.
    """
    client = _phoenix_client()
    explanation = (
        f"{result.rationale} "
        f"[passed: {', '.join(k for k, v in result.criteria.items() if v) or 'none'}; "
        f"failed: {', '.join(k for k, v in result.criteria.items() if not v) or 'none'}]"
    )
    inserted = client.spans.add_span_annotation(
        span_id=span_id,
        annotation_name=ANNOTATION_NAME,
        annotator_kind="LLM",
        score=result.score,
        label=result.label,
        explanation=explanation,
        sync=True,
    )
    return (inserted or {}).get("id", "")


def read_plan_quality(span_ids: list[str]) -> list[dict]:
    """Read back `plan_quality` annotations for the given spans (demo verifier)."""
    client = _phoenix_client()
    anns = client.spans.get_span_annotations(
        span_ids=span_ids, project_identifier=_project(),
        include_annotation_names=[ANNOTATION_NAME])
    return anns


def read_eval_history(limit: int = 5) -> dict:
    """Read your own most recent match-day plan evaluations from Phoenix.

    Returns your recent `plan_quality` scores (0..1) and the judge's explanation of
    what was right or wrong with each plan, newest first. Call this BEFORE planning so
    you can spot recurring weaknesses in your past plans and fix them this time.

    Args:
        limit: How many recent evaluations to return (default 5).

    Returns:
        A dict ``{"evaluations": [{"score", "label", "explanation"}, ...]}`` newest first,
        or an empty list if no plans have been evaluated yet.
    """
    client = _phoenix_client()
    proj = _project()
    spans = client.spans.get_spans(
        project_identifier=proj, name="match_day_plan", limit=max(limit * 3, 15))
    spans = [s for s in spans if s.get("context", {}).get("span_id")]
    spans.sort(key=lambda s: s.get("start_time", ""), reverse=True)
    span_ids = [s["context"]["span_id"] for s in spans]
    if not span_ids:
        return {"evaluations": [], "note": "no past evaluations found yet"}
    order = {s["context"]["span_id"]: s.get("start_time", "") for s in spans}
    anns = client.spans.get_span_annotations(
        span_ids=span_ids, project_identifier=proj,
        include_annotation_names=[ANNOTATION_NAME])
    evals = []
    for a in anns:
        r = a.get("result") or {}
        evals.append({
            "score": r.get("score"),
            "label": r.get("label"),
            "explanation": r.get("explanation"),
            "_t": order.get(a.get("span_id"), ""),
        })
    evals.sort(key=lambda e: e["_t"], reverse=True)
    for e in evals:
        e.pop("_t", None)
    return {"evaluations": evals[:limit]}
