"""Individual-plan (IP) billing lookups."""

from google.adk.tools import ToolContext

from app.tools.members import _get_member


def get_billing_impl(member_id: str) -> dict:
    try:
        member = _get_member(member_id)
    except KeyError as exc:
        return {"error": str(exc)}
    if not member.get("individual_plan"):
        return {"error": "not individual plan"}
    billing = dict(member["billing"])
    billing["member_id"] = member_id
    billing["plan"] = member["plan"]
    return billing


def get_billing(tool_context: ToolContext) -> dict:
    """Return billing details for the current member: premium, autopay day,
    last payment date, and last payment status.

    Only individual-plan (IP) members pay VSP directly. For an
    employer-sponsored member this returns {"error": "not individual
    plan"} -- treat that as a signal the question is out of scope for this
    member (redirect them to their employer's benefits contact), not as a
    failure to retry.
    """
    member_id = tool_context.state.get("member_id")
    if not member_id:
        return {"error": "no member_id bound to this session"}
    return get_billing_impl(member_id)
