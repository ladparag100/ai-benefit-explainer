"""Were the right tools called inside the specialists, with the right args?

Order-insensitive "contains" matching, the same semantics as ADK's
tool_trajectory_avg_score in ANY_ORDER mode: extra calls are fine (a
specialist re-checking the profile isn't a bug), missing or forbidden calls
are not.
"""

from evals.harness.runner import CaseTrace, ToolCall
from evals.scorers.base import Score


def _matches(spec: dict, call: ToolCall) -> bool:
    if call.tool != spec["name"]:
        return False
    for arg, needle in spec.get("args_contain", {}).items():
        value = call.args.get(arg)
        if value is None or needle.lower() not in str(value).lower():
            return False
    for arg in spec.get("args_absent", []):
        if call.args.get(arg) not in (None, ""):
            return False
    return True


def score_trajectory(case: dict, trace: CaseTrace) -> Score:
    exp = case["expected"]
    specs, forbidden = exp["tools"], set(exp["forbidden_tools"])
    if not specs and not forbidden:
        return Score.skip("trajectory", "no tool expectations")

    inner = [c for c in trace.tool_calls if not c.is_specialist]
    details = []
    unused = list(inner)
    hits = 0
    for spec in specs:
        match = next((c for c in unused if _matches(spec, c)), None)
        if match is None:
            seen = [f"{c.tool}({c.args})" for c in inner if c.tool == spec["name"]]
            details.append(f"missing {spec}" + (f"; saw {seen}" if seen else ""))
        else:
            hits += 1
            unused.remove(match)  # each expected call consumes one actual call

    bad = [c.tool for c in inner if c.tool in forbidden]
    if bad:
        details.append(f"forbidden tool(s) called: {bad}")

    errors = [f"{c.tool}: {c.error}" for c in inner if c.error]
    if errors:
        details.append(f"tool errors: {errors}")

    score = (hits / len(specs)) if specs else 1.0
    if bad:
        score = 0.0
    return Score("trajectory", passed=not details, score=score, details=details)
