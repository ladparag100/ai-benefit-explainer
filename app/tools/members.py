"""Member profile lookups.

Every tool module in this package follows the same shape: a plain, pure
`_impl` function that takes `member_id` explicitly (easy to unit test, no
ADK dependency), and a thin ADK-tool wrapper that pulls `member_id` off the
session state via `ToolContext` so the model can never supply -- or
hallucinate -- the wrong one.
"""

import json
from functools import lru_cache
from typing import Any

from google.adk.tools import ToolContext

from app.config import DATA_DIR


@lru_cache(maxsize=1)
def _load_members() -> dict[str, Any]:
    with open(DATA_DIR / "members.json") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_plans() -> dict[str, Any]:
    with open(DATA_DIR / "plans.json") as f:
        return json.load(f)


def _get_member(member_id: str) -> dict[str, Any]:
    members = _load_members()
    if member_id not in members:
        raise KeyError(f"Unknown member_id: {member_id}")
    return members[member_id]


def get_member_profile_impl(member_id: str) -> dict:
    try:
        member = _get_member(member_id)
    except KeyError as exc:
        return {"error": str(exc)}
    plan_details = _load_plans().get(member["plan"], {})
    return {**member, "plan_details": plan_details}


def get_member_profile(tool_context: ToolContext) -> dict:
    """Look up the current member's full profile.

    Returns plan, coverage type, copays, frame/contact allowances and
    whether they've been used this benefit period, last exam dates,
    dependents (if any), and plan-level details (network, OON reimbursement
    cap, discounts). Always call this before answering a benefits,
    eligibility, or ID question -- never guess at a member's plan or
    allowance.
    """
    member_id = tool_context.state.get("member_id")
    if not member_id:
        return {"error": "no member_id bound to this session"}
    return get_member_profile_impl(member_id)
