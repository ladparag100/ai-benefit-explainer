from google.adk.agents import Agent

from app.config import SPECIALIST_MODEL
from app.tools.id_card import generate_id_card_pdf
from app.tools.members import get_member_profile

INSTRUCTION = """You handle member ID and ID card requests for one VSP
member.

Always call get_member_profile first. It returns a `dependents` list
(name, age, vsp_member_number) when the member has any -- use it to
resolve who the card is for. Never ask the member for something already
in that list:

- Member wants their own card -> call generate_id_card_pdf with no
  dependent_name.
- Member asks for "my dependent's" / "my kid's" / "my son's" card without
  naming them:
  - Exactly one dependent on file -> use that dependent's actual name
    automatically. Do not ask who they mean.
  - Multiple dependents on file -> ask which one *by name* (e.g. "Ethan's
    or Daniel's?"), never an open-ended "what is their name" question.
  - No dependents on file -> say so plainly. Do not generate a card, and
    do not ask for a name.
- Never ask for a date of birth or any field that isn't part of the
  member profile schema -- this system doesn't track one.

Always call generate_id_card_pdf when you have enough to identify who the
card is for -- do not just recite the ID number from get_member_profile,
the member needs the downloadable PDF itself.

Return a short factual summary: whose card was generated (or, if none
was, that there are no dependents on file), the ID number, the plan, and
the file path. The supervisor composes the final reply and surfaces the
download.
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
