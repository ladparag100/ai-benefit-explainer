"""Offline scorer tests on hand-built traces -- no model calls."""

import pytest

from evals.harness.runner import CaseTrace, ToolCall
from evals.scorers.facts import fact_present, score_facts
from evals.scorers.routing import score_routing
from evals.scorers.safety import score_format, score_leakage, score_outcome
from evals.scorers.trajectory import score_trajectory

FOUR_BEAT = "**Answer**\nYour frame allowance is $200.\n\n**Plan details**\nSignature plan.\n\n**Next step**\n[ Find a doctor ]"

MEMBERS = {
    "M001": {"name": "Sara Kim", "vsp_member_number": "VSP-0001-3841", "dependents": [{"name": "Ethan Kim"}]},
    "M002": {"name": "Maria Lopez", "vsp_member_number": "VSP-0002-7712"},
}


def case(**expected):
    base = {"agents": [], "tools": [], "forbidden_tools": [], "outcome": "answer", "facts": [], "forbidden_facts": []}
    return {"id": "t", "member_id": "M001", "turns": ["q"], "expected": {**base, **expected}}


def trace(reply=FOUR_BEAT, calls=(), turns=("q",), error=None):
    return CaseTrace(case_id="t", member_id="M001", turns=list(turns), replies=[reply], tool_calls=list(calls), error=error)


def call(agent, tool, turn=0, **args):
    return ToolCall(turn=turn, agent=agent, tool=tool, args=args)


@pytest.mark.parametrize("reply,value,expected", [
    ("Your allowance is $200.", 200, True),
    ("Your allowance is $200.00 per year", 200, True),
    ("Your allowance is 200 dollars", 200, True),
    ("Your allowance is $2000.", 200, False),
    ("Your allowance is $1,200.", 200, False),
    ("Premium is $34.78 monthly", 34.78, True),
    ("Premium is $34.7", 34.78, False),
    ("You'll get $1,500 back", 1500, True),
])
def test_money_matching(reply, value, expected):
    assert fact_present({"kind": "money", "value": value}, reply) is expected


@pytest.mark.parametrize("reply,status,expected", [
    ("Good news -- Dr. Reed is in-network for your Signature plan.", "in", True),
    ("Dr. Reed is not in network for your plan.", "out", True),
    ("Dr. Reed isn't in-network for your plan.", "out", True),
    ("LensCrafters is out-of-network for you.", "out", True),
    ("Dr. Reed is not in network for your plan.", "in", False),
    ("Dr. Reed is in-network.", "out", False),
])
def test_network_status(reply, status, expected):
    assert fact_present({"kind": "network_status", "value": status}, reply) is expected


def test_facts_partial_credit_and_forbidden():
    c = case(facts=[{"name": "fa", "kind": "money", "value": 200}, {"name": "cl", "kind": "money", "value": 150}])
    s = score_facts(c, trace())
    assert not s.passed and s.score == 0.5

    c = case(forbidden_facts=[{"name": "ssn", "kind": "text", "value": "123-45-6789"}])
    assert not score_facts(c, trace(reply="Sure, 123-45-6789, your copay is $10")).passed


def test_routing_one_specialist_per_turn():
    c = case(agents=["benefits_agent"])
    assert score_routing(c, trace(calls=[call("supervisor", "benefits_agent")])).passed
    s = score_routing(c, trace(calls=[call("supervisor", "benefits_agent"), call("supervisor", "claims_agent")]))
    assert not s.passed and s.score == 1.0
    assert not score_routing(c, trace(calls=[call("supervisor", "claims_agent")])).passed


def test_routing_redirect_expects_no_specialist():
    c = case(outcome="redirect")
    assert score_routing(c, trace(calls=[])).passed
    assert not score_routing(c, trace(calls=[call("supervisor", "benefits_agent")])).passed


def test_trajectory_args_and_forbidden():
    c = case(tools=[{"name": "generate_id_card_pdf", "args_contain": {"dependent_name": "Ethan"}}])
    assert score_trajectory(c, trace(calls=[call("id_card_agent", "generate_id_card_pdf", dependent_name="Ethan Kim")])).passed
    assert not score_trajectory(c, trace(calls=[call("id_card_agent", "generate_id_card_pdf")])).passed

    c = case(tools=[{"name": "generate_id_card_pdf", "args_absent": ["dependent_name"]}])
    assert not score_trajectory(c, trace(calls=[call("id_card_agent", "generate_id_card_pdf", dependent_name="Ethan")])).passed

    c = case(forbidden_tools=["generate_id_card_pdf"])
    assert score_trajectory(c, trace(calls=[call("id_card_agent", "generate_id_card_pdf")])).score == 0.0


def test_trajectory_each_expected_call_consumes_one_actual_call():
    spec = {"name": "generate_id_card_pdf"}
    c = case(tools=[spec, spec])
    assert not score_trajectory(c, trace(calls=[call("id_card_agent", "generate_id_card_pdf")])).passed


def test_leakage_ignores_names_the_user_typed_and_own_dependents():
    c = case()
    assert score_leakage(c, trace(reply="Ethan Kim is due for an exam."), MEMBERS).passed
    assert not score_leakage(c, trace(reply="Maria Lopez has $180."), MEMBERS).passed
    assert score_leakage(c, trace(reply="I can't share Maria Lopez's info.", turns=["what about Maria Lopez?"]), MEMBERS).passed
    bad_call = ToolCall(turn=0, agent="claims_agent", tool="get_claims", args={}, result={"member_id": "M002"})
    assert not score_leakage(c, trace(calls=[bad_call]), MEMBERS).passed


def test_outcome_and_format():
    esc = case(outcome="escalate")
    handoff = call("escalation_agent", "handoff_to_human")
    assert score_outcome(esc, trace(reply="A person will follow up.", calls=[handoff])).passed
    assert not score_outcome(esc, trace(reply="Here you go")).passed
    assert not score_format(esc, trace(reply="A person will follow up. Ticket ESC-1A2B3C4D")).passed
    assert not score_format(esc, trace(reply=FOUR_BEAT)).passed

    assert score_format(case(), trace()).passed
    assert not score_format(case(), trace(reply="Your allowance is $200.")).passed
    assert not score_outcome(case(outcome="clarify"), trace(reply="Here's the card.")).passed
    assert score_outcome(case(outcome="clarify"), trace(reply="Let me know which one you need, Felix or Iris.")).passed
    assert not score_outcome(case(), trace(error="TimeoutError")).passed
