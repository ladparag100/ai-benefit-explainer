"""Human handoff."""

import uuid
from datetime import datetime, timezone

from google.adk.tools import ToolContext


def handoff_to_human_impl(member_id: str, reason: str, transcript_summary: str) -> dict:
    ticket_id = f"ESC-{uuid.uuid4().hex[:8].upper()}"
    return {
        "status": "escalated",
        "ticket_id": ticket_id,
        "member_id": member_id,
        "reason": reason,
        "transcript_summary": transcript_summary,
        "escalated_at": datetime.now(timezone.utc).isoformat(),
    }


def handoff_to_human(tool_context: ToolContext, reason: str, transcript_summary: str) -> dict:
    """Hand the conversation off to a human agent with full context, so the
    member never has to repeat themselves.

    Use for: explicit complaints or appeals, medical-necessity judgment
    calls that go beyond a documented benefit lookup, low-confidence
    situations, repeated out-of-scope questions after one redirect, or
    whenever the member explicitly asks for a human. Always call this
    instead of guessing.

    Args:
        reason: short machine-readable reason, e.g. "member_requested_human",
            "complaint", "low_confidence", "medical_necessity",
            "repeated_out_of_scope".
        transcript_summary: 1-3 plain-English sentences on what the member
            needs, so a human doesn't have to re-read the whole chat.
    """
    member_id = tool_context.state.get("member_id") or "unknown"
    result = handoff_to_human_impl(member_id, reason, transcript_summary)

    # Same reasoning as app/tools/id_card.py's "pdf_path" stash: this tool
    # runs inside escalation_agent, which the supervisor calls via AgentTool
    # -- AgentTool only merges the specialist's final text back up, so this
    # dict never reaches the supervisor's own event stream on its own.
    # Session state does reach it, via AgentTool's explicit state_delta
    # forwarding, which is why the ticket is stashed here instead -- a plain
    # key, not "temp:"-prefixed (see id_card.py for why that prefix breaks
    # forwarding on the installed google-adk version).
    tool_context.state["escalation_ticket"] = result
    return result
