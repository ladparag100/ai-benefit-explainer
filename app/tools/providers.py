"""Provider directory / find-a-doctor lookups."""

import json
from functools import lru_cache
from typing import Any, Optional

from google.adk.tools import ToolContext

from app.config import DATA_DIR
from app.tools.members import _get_member


@lru_cache(maxsize=1)
def _load_providers() -> list[dict[str, Any]]:
    with open(DATA_DIR / "providers.json") as f:
        return json.load(f)


def find_nearby_doctors_impl(
    member_id: str, limit: int = 10, provider_name: Optional[str] = None
) -> dict:
    try:
        member = _get_member(member_id)
    except KeyError as exc:
        return {"error": str(exc)}

    plan = member["plan"]
    providers = _load_providers()

    if provider_name:
        matches = [p for p in providers if provider_name.lower() in p["name"].lower()]
        if not matches:
            return {"error": f"No provider matching '{provider_name}' found"}
        match = matches[0]
        return {
            "member_plan": plan,
            "provider": match,
            "in_network": plan in match["in_network_plans"],
        }

    in_network = [p for p in providers if plan in p["in_network_plans"]]
    in_network.sort(key=lambda p: p["distance_mi"])
    return {"member_plan": plan, "providers": in_network[:limit]}


def find_nearby_doctors(
    tool_context: ToolContext, limit: int = 10, provider_name: Optional[str] = None
) -> dict:
    """Find in-network doctors near the current member.

    Filters the provider directory to those that accept the member's plan
    and sorts by distance ascending. If `provider_name` is given, instead
    returns that specific provider (case-insensitive substring match) along
    with whether they're in-network for this member's plan -- use this form
    for "is Dr. X in network" / "can I go to Y" questions.

    Args:
        limit: max number of providers to return when browsing (not used
            when provider_name is given).
        provider_name: a specific provider or retailer name to look up.
    """
    member_id = tool_context.state.get("member_id")
    if not member_id:
        return {"error": "no member_id bound to this session"}
    return find_nearby_doctors_impl(member_id, limit, provider_name)
