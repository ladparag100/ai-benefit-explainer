from evals.harness.runner import CaseTrace
from evals.scorers.base import Score
from evals.scorers.facts import score_facts
from evals.scorers.routing import score_routing
from evals.scorers.safety import score_format, score_leakage, score_outcome
from evals.scorers.trajectory import score_trajectory

METRICS = ["routing", "trajectory", "facts", "outcome", "format", "leakage"]


def score_case(case: dict, trace: CaseTrace, members: dict) -> list[Score]:
    return [
        score_routing(case, trace),
        score_trajectory(case, trace),
        score_facts(case, trace),
        score_outcome(case, trace),
        score_format(case, trace),
        score_leakage(case, trace, members),
    ]
