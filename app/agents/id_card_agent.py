from google.adk.agents import Agent

from app.config import SPECIALIST_MODEL
from app.tools.id_card import generate_id_card_pdf
from app.tools.members import get_member_profile

INSTRUCTION = """You handle member ID and ID card requests for one VSP
member.

Call get_member_profile to confirm who you're generating a card for. If
the member is asking for a dependent's card (e.g. "my son's ID"), pass
that dependent's name as dependent_name; otherwise call
generate_id_card_pdf with no dependent_name for the member's own card.

Always call generate_id_card_pdf -- do not just recite the ID number from
get_member_profile, the member needs the downloadable PDF itself.

Return a short factual summary: whose card was generated, the ID number,
the plan, and the file path. The supervisor composes the final reply and
surfaces the download.
"""

id_card_agent = Agent(
    name="id_card_agent",
    model=SPECIALIST_MODEL,
    description=(
        "Returns the member ID and generates a downloadable mock ID card "
        "PDF, for the member or a dependent."
    ),
    instruction=INSTRUCTION,
    tools=[get_member_profile, generate_id_card_pdf],
)
