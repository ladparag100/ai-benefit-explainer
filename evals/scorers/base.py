from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Score:
    """One metric's verdict for one case. `score` is 0..1 (partial credit
    where it makes sense, e.g. 2 of 3 facts found); `passed` is the strict
    pass/fail used for gating. `applicable=False` means the case has nothing
    for this metric to check, so it's left out of that metric's averages."""

    metric: str
    passed: bool
    score: float
    details: list[str] = field(default_factory=list)
    applicable: bool = True

    @classmethod
    def skip(cls, metric: str, reason: Optional[str] = None) -> "Score":
        return cls(metric, True, 1.0, [reason] if reason else [], applicable=False)
