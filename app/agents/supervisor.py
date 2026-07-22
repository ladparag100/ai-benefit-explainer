from google.adk.agents import Agent
from google.adk.tools.agent_tool import AgentTool

from app.agents.benefits_agent import benefits_agent
from app.agents.billing_agent import billing_agent
from app.agents.claims_agent import claims_agent
from app.agents.escalation_agent import escalation_agent
from app.agents.find_doctor_agent import find_doctor_agent
from app.agents.id_card_agent import id_card_agent
from app.config import PROMPTS_DIR, SUPERVISOR_MODEL

SYSTEM_PROMPT = (PROMPTS_DIR / "system_prompt.md").read_text()

# Each specialist is wrapped as an AgentTool rather than passed via
# sub_agents=[...]. sub_agents hands full conversation control to whichever
# specialist the model transfers to; AgentTool runs the specialist to
# completion and returns its result as a tool call, so the supervisor stays
# in control and composes the final four-beat response itself -- which is
# what the spec actually asks for ("receives structured output back, then
# composes the final response").
root_agent = Agent(
    name="supervisor",
    model=SUPERVISOR_MODEL,
    description="Routes VSP member questions to the right specialist and composes the final answer.",
    instruction=SYSTEM_PROMPT,
    tools=[
        AgentTool(agent=benefits_agent),
        AgentTool(agent=id_card_agent),
        AgentTool(agent=find_doctor_agent),
        AgentTool(agent=claims_agent),
        AgentTool(agent=billing_agent),
        AgentTool(agent=escalation_agent),
    ],
)
