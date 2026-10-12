"""Template-based golden eval cases, labelled from the fixture data.

Every expected value here (dollar amounts, provider names, which specialist
and which tools should run) is computed from the same JSON the tools read,
so labels cost nothing and can't drift from the data. Question wording is
varied per case from a small pool of phrasings; LLM paraphrasing for more
linguistic variety is a later layer on top of this, not a replacement.

    python -m evals.generators.golden_cases --per-intent 6 --seed 7

Case schema (one JSON object per line):

    id, member_id, intent, tags, turns: [str, ...],
    expected: {
      agents:          specialists the supervisor must route to
      tools:           [{name, args_contain?: {arg: substring}, args_absent?: [arg]}]
      forbidden_tools: tools that must NOT run
      outcome:         answer | escalate | clarify | redirect | refuse | null
      facts:           [{name, kind: money|text|regex|network_status, value}]
      forbidden_facts: same shape; must NOT appear in the final reply
    },
    judge_notes: what a human / LLM judge should look for beyond the facts
"""

import argparse
import json
import random
from pathlib import Path
from typing import Callable, Iterable, Optional

from evals.paths import DATASETS_DIR, FIXTURES_DIR

NO_DEPENDENTS_RE = (
    r"(no|n't any|not any|zero) (dependents?|family members?|one else)"
    r"|(don't|do not|doesn't|does not) (have|show|list) any (dependents?|family)"
    r"|(only|just) you\b|member[- ]only"
)
NO_CLAIMS_RE = r"(no|n't any|not any|zero) (claims?|visits?)|(don't|do not) (have|see) any claims?"


# ---------------------------------------------------------------- helpers


def money(name: str, value) -> dict:
    return {"name": name, "kind": "money", "value": value}


def text(name: str, value) -> dict:
    return {"name": name, "kind": "text", "value": value}


def regex(name: str, value: str) -> dict:
    return {"name": name, "kind": "regex", "value": value}


def tool(name: str, args_contain: Optional[dict] = None, args_absent: Optional[list] = None) -> dict:
    spec = {"name": name}
    if args_contain:
        spec["args_contain"] = args_contain
    if args_absent:
        spec["args_absent"] = args_absent
    return spec


def expected(agents, tools=(), forbidden_tools=(), outcome="answer", facts=(), forbidden_facts=()) -> dict:
    return {
        "agents": list(agents),
        "tools": list(tools),
        "forbidden_tools": list(forbidden_tools),
        "outcome": outcome,
        "facts": list(facts),
        "forbidden_facts": list(forbidden_facts),
    }


def first_name(full: str) -> str:
    return full.split()[0]


def provider_key(name: str) -> str:
    """The token a correct provider_name tool arg must contain: the surname
    for "Dr. First Last, OD", otherwise the brand (first word)."""
    if name.startswith("Dr. "):
        return name.split(",")[0].split()[-1]
    return name.split()[0]


def provider_short(name: str) -> str:
    return name.split(",")[0].split(" - ")[0]


def deps(m: dict) -> list:
    return m.get("dependents", [])


def contacts_used(m: dict) -> bool:
    return bool(m.get("contact_allowance_used", {}).get("self"))


BENEFITS = ["benefits_agent"]
BENEFITS_TOOLS = [tool("get_member_profile"), tool("query_knowledge")]


# ---------------------------------------------------------------- intents
# Each intent: (eligibility predicate, builder(member, ctx, rng) -> (turns, expected, judge_notes))


def _frame_allowance(m, ctx, rng):
    q = rng.choice([
        "How much do I get toward new frames?",
        "what's my frame allowance",
        "If I buy glasses, how much will my plan cover for the frames?",
    ])
    return [q], expected(BENEFITS, BENEFITS_TOOLS, facts=[money("frame_allowance", m["frame_allowance"])]), \
        "States the frame allowance; may mention the featured-frame bonus."


def _exam_copay(m, ctx, rng):
    q = rng.choice(["What's my copay for an eye exam?", "how much do i pay for an eye exam", "Is my annual eye exam free?"])
    return [q], expected(BENEFITS, BENEFITS_TOOLS, facts=[money("exam_copay", m["copays"]["exam"])]), \
        "States the exam copay for this member's plan."


def _contact_allowance(m, ctx, rng):
    q = rng.choice(["How much will my plan pay for contacts?", "what's my contact lens allowance?"])
    return [q], expected(BENEFITS, BENEFITS_TOOLS, facts=[money("contact_allowance", m["contact_allowance"])]), \
        "States the contact allowance; ideally notes contacts are instead of glasses for the period."


def _overview(m, ctx, rng):
    q = rng.choice(["Tell me about my benefits.", "Can you explain my plan?", "what's my coverage"])
    return [q], expected(
        BENEFITS, BENEFITS_TOOLS,
        facts=[text("plan", m["plan"]), money("frame_allowance", m["frame_allowance"]), money("exam_copay", m["copays"]["exam"])],
    ), "Gives a real overview without first asking what the member wants to know."


def _oon(m, ctx, rng):
    oon = ctx["plans"][m["plan"]]["oon_exam_reimbursement"]
    q = rng.choice([
        "If I see an out-of-network eye doctor, how much do I get reimbursed for the exam?",
        "What do I get back for an exam at a doctor that isn't in network?",
    ])
    return [q], expected(BENEFITS, BENEFITS_TOOLS, facts=[money("oon_exam_reimbursement", oon)]), \
        "States the out-of-network exam reimbursement cap."


def _in_lieu(m, ctx, rng):
    q = rng.choice(["Can I use my frame allowance for new glasses this year?", "I want new glasses -- am I covered right now?"])
    return [q], expected(BENEFITS, BENEFITS_TOOLS, facts=[regex("mentions_contacts", r"contact")]), \
        "Explains that contacts were already used this period, so glasses aren't covered until the next period, in plain language."


def _dependent_none(m, ctx, rng):
    q = rng.choice(["What benefits does my dependent have?", "Is my kid covered on my plan?"])
    return [q], expected(BENEFITS, [tool("get_member_profile")], forbidden_tools=["generate_id_card_pdf"],
                         facts=[regex("says_no_dependents", NO_DEPENDENTS_RE)]), \
        "Says plainly there are no dependents on file; does not ask for a name."


def _dependent_single(m, ctx, rng):
    d = deps(m)[0]
    q = rng.choice(["When was my dependent's last eye exam?", "Is my family member due for an eye exam?"])
    return [q], expected(BENEFITS, [tool("get_member_profile")], facts=[text("dependent_name", first_name(d["name"]))]), \
        "Answers using the one dependent's actual name and last-exam date without asking who they mean."


def _dependent_multi(m, ctx, rng):
    q = "When did the other people on my plan last have an eye exam?"
    facts = [text(f"dependent_{i}", first_name(d["name"])) for i, d in enumerate(deps(m))]
    return [q], expected(BENEFITS, [tool("get_member_profile")], facts=facts), \
        "Lists each dependent by name with their last exam date."


def _id_card_self(m, ctx, rng):
    q = rng.choice(["Can I get a copy of my ID card?", "I need my member ID card", "what's my member ID?"])
    return [q], expected(
        ["id_card_agent"],
        [tool("get_member_profile"), tool("generate_id_card_pdf", args_absent=["dependent_name"])],
        facts=[text("member_number", m["vsp_member_number"])],
    ), "Generates the member's own card and states their member number."


def _id_card_dep_single(m, ctx, rng):
    d = deps(m)[0]
    q = rng.choice(["Can I get an ID card for my dependent?", "I need the ID card for the other person on my plan."])
    return [q], expected(
        ["id_card_agent"],
        [tool("get_member_profile"), tool("generate_id_card_pdf", args_contain={"dependent_name": first_name(d["name"])})],
        facts=[text("dependent_name", first_name(d["name"]))],
    ), "Uses the single dependent automatically -- never asks who they mean."


def _id_card_dep_multi(m, ctx, rng):
    q = "I need my dependent's ID card."
    facts = [text(f"dependent_{i}", first_name(d["name"])) for i, d in enumerate(deps(m))]
    return [q], expected(["id_card_agent"], [tool("get_member_profile")], forbidden_tools=["generate_id_card_pdf"],
                         outcome="clarify", facts=facts), \
        "Asks which dependent *by name*, not an open-ended 'what is their name'."


def _id_card_dep_none(m, ctx, rng):
    q = "Can I get an ID card for my dependent?"
    return [q], expected(["id_card_agent"], [tool("get_member_profile")], forbidden_tools=["generate_id_card_pdf"],
                         facts=[regex("says_no_dependents", NO_DEPENDENTS_RE)]), \
        "Says there are no dependents on file; doesn't generate a card or ask for a name."


def _find_doctor(m, ctx, rng):
    in_net = sorted((p for p in ctx["providers"] if m["plan"] in p["in_network_plans"]), key=lambda p: p["distance_mi"])
    q = rng.choice(["Find me an eye doctor near me.", "Who's in network close to me?", "where can i get an eye exam nearby"])
    return [q], expected(
        ["find_doctor_agent"], [tool("find_nearby_doctors", args_absent=["provider_name"])],
        facts=[text("nearest_provider", provider_short(in_net[0]["name"]))],
    ), "Lists in-network providers nearest first."


def _named_provider(m, ctx, rng):
    p = rng.choice(ctx["providers"])
    in_network = m["plan"] in p["in_network_plans"]
    q = rng.choice(["Is {} in network for me?", "Can I go to {} with my plan?"]).format(provider_short(p["name"]))
    return [q], expected(
        ["find_doctor_agent"], [tool("find_nearby_doctors", args_contain={"provider_name": provider_key(p["name"])})],
        facts=[{"name": "network_status", "kind": "network_status", "value": "in" if in_network else "out"}],
    ), f"Says {p['name']} is {'in' if in_network else 'NOT in'} network for the {m['plan']} plan."


def _latest_claim(m, ctx, rng):
    claim = max(ctx["claims_by_member"][m["member_id"]], key=lambda c: c["date"])
    status_word = "pending" if claim["status"] == "Pending" else "processed"
    q = rng.choice(["What's the status of my most recent claim?", "Has my last claim gone through?"])
    return [q], expected(["claims_agent"], [tool("get_claims")],
                         facts=[text("status", status_word), money("plan_paid", claim["plan_paid"])]), \
        "Gives the latest claim's status, provider and what the plan paid."


def _no_claims(m, ctx, rng):
    q = rng.choice(["Do I have any claims on file?", "Can you show me my claim history?"])
    return [q], expected(["claims_agent"], [tool("get_claims")], facts=[regex("says_no_claims", NO_CLAIMS_RE)]), \
        "Says plainly there are no claims on file; treats it as normal, not an error."


def _billing_ip(m, ctx, rng):
    b = m["billing"]
    q = rng.choice(["When does my autopay run and how much is it?", "What's my monthly premium and when is it charged?"])
    return [q], expected(["billing_agent"], [tool("get_billing")],
                         facts=[money("premium", b["premium"]), regex("autopay_day", rf"\b{b['autopay_day']}(st|nd|rd|th)?\b")]), \
        "States premium and autopay day from billing data."


def _billing_employer(m, ctx, rng):
    q = rng.choice(["How much is my monthly premium?", "When is my next payment due?"])
    return [q], expected(["billing_agent"], [tool("get_billing")], facts=[regex("mentions_employer", r"employer")]), \
        "Explains billing goes through their employer; doesn't invent a premium."


def _escalate_human(m, ctx, rng):
    q = rng.choice(["I'd like to talk to a real person, please.", "Can you connect me with a human agent?"])
    return [q], expected(["escalation_agent"], [tool("handoff_to_human")], outcome="escalate"), \
        "Acknowledges the request; says a person will follow up with context; no headers, no ticket ID."


def _escalate_complaint(m, ctx, rng):
    q = "I was charged for an exam that should have been covered and I want to file a complaint."
    return [q], expected(["escalation_agent"], [tool("handoff_to_human")], outcome="escalate"), \
        "Escalates the complaint instead of answering it."


def _off_topic(m, ctx, rng):
    q = rng.choice(["Who won the World Series last year?", "Can you give me a good lasagna recipe?"])
    return [q], expected([], forbidden_tools=["handoff_to_human"], outcome="redirect",
                         facts=[regex("redirects_to_vision", r"vision|benefit")]), \
        "One short friendly redirect; no specialist, no escalation."


def _followup_contacts(m, ctx, rng):
    turns = ["What's my frame allowance?", "And what about contacts?"]
    return turns, expected(BENEFITS, BENEFITS_TOOLS, facts=[money("contact_allowance", m["contact_allowance"])]), \
        "Second turn resolves 'what about contacts' from context and gives the contact allowance."


def _followup_dep_card(m, ctx, rng):
    d = deps(m)[0]
    turns = ["Can I get my ID card?", f"Can I get one for {first_name(d['name'])} too?"]
    return turns, expected(
        ["id_card_agent"],
        [tool("generate_id_card_pdf", args_absent=["dependent_name"]),
         tool("generate_id_card_pdf", args_contain={"dependent_name": first_name(d["name"])})],
        facts=[text("dependent_name", first_name(d["name"]))],
    ), "Generates both cards across the two turns without re-asking anything."


INTENTS: dict[str, tuple[Callable[[dict, dict], bool], Callable, list[str]]] = {
    "benefits.frame_allowance": (lambda m, c: not contacts_used(m), _frame_allowance, ["benefits"]),
    "benefits.exam_copay": (lambda m, c: True, _exam_copay, ["benefits"]),
    "benefits.contact_allowance": (lambda m, c: not contacts_used(m), _contact_allowance, ["benefits"]),
    "benefits.overview": (lambda m, c: True, _overview, ["benefits", "broad"]),
    "benefits.oon_reimbursement": (lambda m, c: True, _oon, ["benefits", "oon"]),
    "benefits.in_lieu_of": (lambda m, c: contacts_used(m), _in_lieu, ["benefits", "edge"]),
    "dependents.none": (lambda m, c: not deps(m), _dependent_none, ["dependents", "edge"]),
    "dependents.single": (lambda m, c: len(deps(m)) == 1, _dependent_single, ["dependents"]),
    "dependents.multiple": (lambda m, c: len(deps(m)) > 1, _dependent_multi, ["dependents"]),
    "id_card.self": (lambda m, c: True, _id_card_self, ["id_card"]),
    "id_card.dependent_single": (lambda m, c: len(deps(m)) == 1, _id_card_dep_single, ["id_card", "dependents"]),
    "id_card.dependent_multiple": (lambda m, c: len(deps(m)) > 1, _id_card_dep_multi, ["id_card", "dependents", "clarify"]),
    "id_card.dependent_none": (lambda m, c: not deps(m), _id_card_dep_none, ["id_card", "dependents", "edge"]),
    "find_doctor.nearby": (lambda m, c: True, _find_doctor, ["find_doctor"]),
    "find_doctor.named_provider": (lambda m, c: True, _named_provider, ["find_doctor"]),
    "claims.latest": (lambda m, c: bool(c["claims_by_member"].get(m["member_id"])), _latest_claim, ["claims"]),
    "claims.none": (lambda m, c: not c["claims_by_member"].get(m["member_id"]), _no_claims, ["claims", "edge"]),
    "billing.individual_plan": (lambda m, c: bool(m.get("individual_plan")), _billing_ip, ["billing"]),
    "billing.employer_sponsored": (lambda m, c: not m.get("individual_plan"), _billing_employer, ["billing", "edge"]),
    "escalation.human_request": (lambda m, c: True, _escalate_human, ["escalation"]),
    "escalation.complaint": (lambda m, c: True, _escalate_complaint, ["escalation"]),
    "guardrails.off_topic": (lambda m, c: True, _off_topic, ["guardrails"]),
    "multiturn.followup_contacts": (lambda m, c: not contacts_used(m), _followup_contacts, ["multiturn", "benefits"]),
    "multiturn.followup_dependent_card": (lambda m, c: len(deps(m)) >= 1, _followup_dep_card, ["multiturn", "id_card"]),
}


def load_context(data_dir: Path) -> dict:
    def load(name):
        with open(data_dir / name) as f:
            return json.load(f)

    claims_by_member: dict = {}
    for claim in load("claims.json"):
        claims_by_member.setdefault(claim["member_id"], []).append(claim)
    return {
        "members": load("members.json"),
        "plans": load("plans.json"),
        "providers": load("providers.json"),
        "claims_by_member": claims_by_member,
    }


def generate_cases(ctx: dict, per_intent: int, seed: int, smoke_per_intent: int = 1) -> Iterable[dict]:
    rng = random.Random(seed)
    members = list(ctx["members"].values())
    for intent, (eligible, build, tags) in INTENTS.items():
        pool = [m for m in members if eligible(m, ctx)]
        # Spread across plans first so a small per_intent still covers each plan.
        rng.shuffle(pool)
        pool.sort(key=lambda m: m["plan"])
        by_plan: dict = {}
        for m in pool:
            by_plan.setdefault(m["plan"], []).append(m)
        round_robin = [m for group in zip_longest_lists(by_plan.values()) for m in group]
        for n, member in enumerate(round_robin[:per_intent]):
            turns, exp, notes = build(member, ctx, rng)
            case_tags = list(tags) + [f"plan:{member['plan']}", "multi-turn" if len(turns) > 1 else "single-turn"]
            if n < smoke_per_intent:
                case_tags.append("smoke")
            yield {
                "id": f"{intent}#{n + 1:02d}",
                "member_id": member["member_id"],
                "intent": intent,
                "tags": case_tags,
                "turns": turns,
                "expected": exp,
                "judge_notes": notes,
            }


def zip_longest_lists(groups) -> list[list]:
    groups = [list(g) for g in groups]
    out = []
    while any(groups):
        out.append([g.pop(0) for g in groups if g])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=FIXTURES_DIR)
    parser.add_argument("--per-intent", type=int, default=6)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=DATASETS_DIR / "golden_v1.jsonl")
    args = parser.parse_args()

    ctx = load_context(args.data_dir)
    cases = list(generate_cases(ctx, args.per_intent, args.seed))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w") as f:
        for case in cases:
            f.write(json.dumps(case) + "\n")
    smoke = sum("smoke" in c["tags"] for c in cases)
    print(f"Wrote {len(cases)} cases ({smoke} tagged smoke) across {len(INTENTS)} intents to {args.out}")


if __name__ == "__main__":
    main()
