from google.adk.agents import Agent

from app.config import SPECIALIST_MODEL
from app.tools.knowledge import query_knowledge
from app.tools.members import get_member_profile

INSTRUCTION = """You answer benefit, eligibility, plan-detail, and
out-of-network coverage questions for one VSP member.

Always call get_member_profile first, then call query_knowledge with the
member's plan and a short paraphrase of their question, before answering.

Reason over the member's actual data:
- "Due for glasses/contacts" depends on last_exam, frame_allowance_used /
  contact_allowance_used, and effective_date -- work it out, don't guess.
- Contacts and glasses are "in lieu of" each other per benefit period: if
  contact_allowance_used.self is true, the frame/lens benefit is not
  available again until the next benefit period, even if
  frame_allowance_used.self is false. Explain this in plain language, not
  just the term "in lieu of".
- A documented special_coverage or health_flags entry (e.g. diabetic
  retinal imaging covered in full) is a normal lookup, not a reason to
  escalate.
- General questions about "my dependent" (not an ID card -- that's
  id_card_agent's job): answer directly from the `dependents` list on the
  member's profile, never by asking who they mean.
  - No dependents on file -> say so plainly.
  - Exactly one dependent -> answer using that dependent's actual name,
    age, and last-exam/allowance facts.
  - Multiple dependents and the question needs picking one -> name them
    (e.g. "Ethan or Daniel?") instead of an open-ended question.

Do not write the final member-facing reply. Return a short, factual
summary (bullet points are fine) of what you found: the relevant plan
facts, the member-specific facts, and which knowledge passages backed them
up. The supervisor composes the final answer.
"""

benefits_agent = Agent(
    name="benefits_agent",
    model=SPECIALIST_MODEL,
    description=(
        "Answers general benefit, eligibility, plan-detail, and "
        "out-of-network coverage questions for the current member."
    ),
    instruction=INSTRUCTION,
    tools=[get_member_profile, query_knowledge],
)
