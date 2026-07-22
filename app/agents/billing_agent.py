from google.adk.agents import Agent

from app.config import SPECIALIST_MODEL
from app.tools.billing import get_billing

INSTRUCTION = """You answer billing questions -- premium, autopay day,
next payment, payment method -- for individual-plan (IP) members only.

Always call get_billing. If it returns {"error": "not individual plan"},
say so plainly in your summary: this member's coverage is
employer-sponsored, they don't pay VSP directly, and this question is out
of scope for them. Do not retry the call or invent billing figures.

Return a short factual summary, not a full reply. The supervisor composes
the final answer.
"""

billing_agent = Agent(
    name="billing_agent",
    model=SPECIALIST_MODEL,
    description="Answers billing and autopay questions for individual-plan members only.",
    instruction=INSTRUCTION,
    tools=[get_billing],
)
