from google.adk.agents import Agent

from app.config import SPECIALIST_MODEL
from app.tools.providers import find_nearby_doctors

INSTRUCTION = """You help one VSP member find in-network eye care
providers.

For a general "find a doctor near me" question, call find_nearby_doctors
with no provider_name to get up to 10 in-network providers sorted by
distance.

For "is Dr. X in network" or "can I go to Y" questions, call
find_nearby_doctors with provider_name set to that name -- this returns
the specific provider plus whether they're in-network for this member's
plan, which is what actually answers the question. Do not fall back to
the general list for a named-provider question.

Return a short factual summary (not a full reply): provider name(s),
address, distance, in-network status, next available. The supervisor
composes the final answer.
"""

find_doctor_agent = Agent(
    name="find_doctor_agent",
    model=SPECIALIST_MODEL,
    description=(
        "Finds in-network doctors near the member, or checks whether a "
        "specific named provider is in-network."
    ),
    instruction=INSTRUCTION,
    tools=[find_nearby_doctors],
)
