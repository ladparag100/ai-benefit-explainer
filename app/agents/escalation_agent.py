from google.adk.agents import Agent

from app.config import SPECIALIST_MODEL
from app.tools.escalation import handoff_to_human

INSTRUCTION = """You hand the conversation off to a human on behalf of one
VSP member.

Always call handoff_to_human with a short machine-readable reason (e.g.
"member_requested_human", "complaint", "low_confidence",
"medical_necessity", "repeated_out_of_scope") and a 1-3 sentence
transcript_summary of what the member actually needs -- written so a
human picking this up doesn't have to re-read the whole conversation.

Return the ticket_id and a short factual summary. The supervisor composes
the member-facing reply.
"""

escalation_agent = Agent(
    name="escalation_agent",
    model=SPECIALIST_MODEL,
    description=(
        "Hands off to a human with full context: complaints, appeals, "
        "medical necessity, low confidence, or explicit human requests."
    ),
    instruction=INSTRUCTION,
    tools=[handoff_to_human],
)
