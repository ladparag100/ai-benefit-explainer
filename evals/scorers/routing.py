"""Did the supervisor route to the right specialist(s), one per turn?"""

from evals.harness.runner import CaseTrace
from evals.scorers.base import Score


def score_routing(case: dict, trace: CaseTrace) -> Score:
    expected = set(case["expected"]["agents"])
    called = [c.tool for c in trace.tool_calls if c.is_specialist and c.agent == "supervisor"]
    details = []

    missing = expected - set(called)
    if missing:
        details.append(f"not routed to: {sorted(missing)} (got {called or 'none'})")

    # outcome=redirect/refuse means "no specialist at all".
    if not expected and case["expected"]["outcome"] in ("redirect", "refuse") and called:
        details.append(f"expected no specialist, got {called}")

    unexpected = set(called) - expected
    if expected and unexpected:
        details.append(f"also routed to: {sorted(unexpected)}")

    # System prompt rule: exactly one specialist per turn.
    per_turn: dict[int, int] = {}
    for c in trace.tool_calls:
        if c.is_specialist and c.agent == "supervisor":
            per_turn[c.turn] = per_turn.get(c.turn, 0) + 1
    over = {t: n for t, n in per_turn.items() if n > 1}
    if over:
        details.append(f"more than one specialist in turn(s): {over}")

    if not expected and case["expected"]["outcome"] not in ("redirect", "refuse"):
        return Score.skip("routing", "no routing expectation")

    # Partial credit = share of expected specialists reached; any extra or
    # duplicate routing still fails `passed`.
    score = len(expected - missing) / len(expected) if expected else float(not called)
    return Score("routing", passed=not details, score=score, details=details)
