"""Offline checks that the generators are deterministic and their labels
agree with what the real tool implementations return for the same data."""

import json

import pytest

from evals.generators.golden_cases import INTENTS, generate_cases, load_context
from evals.generators.synthetic_data import build_members, write_fixtures


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory):
    return write_fixtures(tmp_path_factory.mktemp("fixtures"), count=24, seed=7)


@pytest.fixture(scope="module")
def ctx(fixture_dir):
    return load_context(fixture_dir)


def test_synthetic_members_are_deterministic():
    assert build_members(12, seed=3) == build_members(12, seed=3)
    assert build_members(12, seed=3) != build_members(12, seed=4)


def test_synthetic_members_have_unique_names_and_numbers(ctx):
    members = list(ctx["members"].values())
    assert len({m["name"] for m in members}) == len(members)
    assert len({m["vsp_member_number"] for m in members}) == len(members)


def test_synthetic_amounts_match_plan_table(ctx):
    for m in ctx["members"].values():
        if m["member_id"].startswith("SYN-"):
            plan = ctx["plans"][m["plan"]]
            assert m["frame_allowance"] == plan["frame_allowance"]
            assert m["contact_allowance"] == plan["contact_allowance"]
            assert m["copays"]["exam"] == plan["exam_copay"]


def test_every_intent_gets_cases(ctx):
    cases = list(generate_cases(ctx, per_intent=6, seed=7))
    assert {c["intent"] for c in cases} == set(INTENTS)
    assert len({c["id"] for c in cases}) == len(cases)


def test_labels_agree_with_tool_impls(fixture_dir, ctx, monkeypatch):
    """The tools read app.config.DATA_DIR at call time via lru_cached
    loaders -- point them at the fixtures and compare against the labels."""
    from app.tools import claims, members, providers

    for mod in (members, claims, providers):
        monkeypatch.setattr(mod, "DATA_DIR", fixture_dir)
    for loader in (members._load_members, members._load_plans, claims._load_claims, providers._load_providers):
        loader.cache_clear()
    try:
        for case in generate_cases(ctx, per_intent=6, seed=7):
            facts = {f["name"]: f["value"] for f in case["expected"]["facts"]}
            mid = case["member_id"]
            if case["intent"] == "benefits.frame_allowance":
                assert members.get_member_profile_impl(mid)["frame_allowance"] == facts["frame_allowance"]
            if case["intent"] == "find_doctor.nearby":
                nearest = providers.find_nearby_doctors_impl(mid)["providers"][0]["name"]
                assert nearest.startswith(facts["nearest_provider"])
            if case["intent"] == "find_doctor.named_provider":
                arg = case["expected"]["tools"][0]["args_contain"]["provider_name"]
                result = providers.find_nearby_doctors_impl(mid, provider_name=arg)
                assert ("in" if result["in_network"] else "out") == facts["network_status"]
            if case["intent"] == "claims.none":
                assert claims.get_claims_impl(mid)["claims"] == []
    finally:
        for loader in (members._load_members, members._load_plans, claims._load_claims, providers._load_providers):
            loader.cache_clear()


def test_checked_in_datasets_are_valid_jsonl():
    from evals.paths import DATASETS_DIR

    for path in DATASETS_DIR.glob("*.jsonl"):
        for line in path.read_text().splitlines():
            case = json.loads(line)
            assert {"id", "member_id", "turns", "expected"} <= case.keys()
            assert {"agents", "tools", "forbidden_tools", "outcome", "facts", "forbidden_facts"} <= case["expected"].keys()
