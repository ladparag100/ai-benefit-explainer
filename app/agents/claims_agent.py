from google.adk.agents import Agent

from app.config import SPECIALIST_MODEL
from app.tools.claims import get_claims

INSTRUCTION = """You answer claim-history questions for one VSP member:
has a claim been processed, what did the plan cover, claim history
overall.

Always call get_claims. An empty claims list is a normal, valid result --
say so plainly, it is not an error. If the member has a "Pending" claim,
note that reimbursement typically processes within 30 days, and a pending
claim older than that is worth flagging as a possible escalation.

Return a short factual summary of the relevant claim(s): date, provider,
service, what the plan paid, what the member paid, status. The supervisor
composes the final reply.
"""

claims_agent = Agent(
    name="claims_agent",
    model=SPECIALIST_MODEL,
    description="Answers claim status and claim history questions for the current member.",
    instruction=INSTRUCTION,
    tools=[get_claims],
)
