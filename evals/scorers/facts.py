"""Are the expected facts in the final reply, and the forbidden ones absent?

This is the highest-value check in the suite: the costliest failure mode for
a benefits explainer is a confidently wrong dollar amount, and that's
checkable exactly against the data -- no LLM judge needed.
"""

import re

from evals.harness.runner import CaseTrace
from evals.scorers.base import Score

_NOT_IN_NETWORK = re.compile(
    r"(not|isn't|is not|aren't|are not|n't)\s+(an?\s+)?(in[- ]network|in your network|in[- ]network provider|part of|covered|participating)"
    r"|out[- ]of[- ]network",
    re.IGNORECASE,
)
_IN_NETWORK = re.compile(r"\bin[- ]network\b|\bin your network\b|\bparticipating\b", re.IGNORECASE)


def _money_pattern(value) -> re.Pattern:
    amount = float(value)
    if amount.is_integer():
        num = rf"{int(amount):,}".replace(",", ",?") + r"(?:\.00)?"
    else:
        num = re.escape(f"{amount:.2f}")
    # "$200", "$ 200.00", "200 dollars" -- but not "$2000" or "1200".
    end = r"(?!\d|,\d|\.\d)"  # no more digits after the amount
    return re.compile(rf"(?:\$\s?{num}{end}|(?<![\d.,$]){num}\s?(?:dollars|USD))", re.IGNORECASE)


def fact_present(fact: dict, reply: str) -> bool:
    kind, value = fact["kind"], fact["value"]
    if kind == "money":
        return bool(_money_pattern(value).search(reply))
    if kind == "text":
        options = value if isinstance(value, list) else [value]
        return any(str(v).lower() in reply.lower() for v in options)
    if kind == "regex":
        return bool(re.search(value, reply, re.IGNORECASE))
    if kind == "network_status":
        says_out = bool(_NOT_IN_NETWORK.search(reply))
        says_in = bool(_IN_NETWORK.search(_NOT_IN_NETWORK.sub("", reply)))
        return (says_out and not says_in) if value == "out" else (says_in and not says_out)
    raise ValueError(f"unknown fact kind: {kind}")


def score_facts(case: dict, trace: CaseTrace) -> Score:
    exp = case["expected"]
    if not exp["facts"] and not exp["forbidden_facts"]:
        return Score.skip("facts", "no fact expectations")

    reply = trace.final_reply
    details = []
    found = 0
    for fact in exp["facts"]:
        if fact_present(fact, reply):
            found += 1
        else:
            details.append(f"missing {fact['name']}={fact['value']!r}")
    for fact in exp["forbidden_facts"]:
        if fact_present(fact, " ".join(trace.replies)):
            details.append(f"forbidden {fact['name']} present")

    score = found / len(exp["facts"]) if exp["facts"] else 1.0
    if any(d.startswith("forbidden") for d in details):
        score = 0.0
    return Score("facts", passed=not details, score=score, details=details)
