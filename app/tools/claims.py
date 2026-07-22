"""Claims history lookups."""

import json
from functools import lru_cache
from typing import Any

from google.adk.tools import ToolContext

from app.config import DATA_DIR
from app.tools.members import _get_member


@lru_cache(maxsize=1)
def _load_claims() -> list[dict[str, Any]]:
    with open(DATA_DIR / "claims.json") as f:
        return json.load(f)


def get_claims_impl(member_id: str) -> dict:
    try:
        _get_member(member_id)
    except KeyError as exc:
        return {"error": str(exc)}
    claims = [c for c in _load_claims() if c["member_id"] == member_id]
    return {"member_id": member_id, "claims": claims}


def get_claims(tool_context: ToolContext) -> dict:
    """Return the current member's claim history.

    Each claim has a date, provider, service, what the plan paid, what the
    member paid, and status (Processed / Pending / "Processed (OON
    reimbursement)"). An empty list is a normal, valid answer for a member
    with no claims on file -- not an error.
    """
    member_id = tool_context.state.get("member_id")
    if not member_id:
        return {"error": "no member_id bound to this session"}
    return get_claims_impl(member_id)
