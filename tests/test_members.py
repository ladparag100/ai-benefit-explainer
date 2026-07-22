from app.tools.members import get_member_profile_impl


def test_all_six_members_resolve(all_member_ids):
    for member_id in all_member_ids:
        profile = get_member_profile_impl(member_id)
        assert "error" not in profile
        assert profile["member_id"] == member_id


def test_unknown_member_returns_error():
    profile = get_member_profile_impl("M999")
    assert "error" in profile


def test_maria_due_for_glasses_facts_present():
    """Maria (Choice): last used frame allowance Jul 2024, plan renewed Jan
    2026 -- the facts an agent needs to conclude she's due, without the
    tool itself pre-deciding the answer."""
    profile = get_member_profile_impl("M002")
    assert profile["plan"] == "Choice"
    assert profile["frame_allowance_used"]["last_used"] == "2024-07-12"
    assert profile["frame_allowance_used"]["self"] is False


def test_priya_contacts_used_blocks_frame_eligibility():
    profile = get_member_profile_impl("M005")
    assert profile["contact_allowance_used"]["self"] is True
    assert profile["frame_allowance_used"]["eligible_this_year"] is False


def test_robert_retinal_imaging_special_coverage():
    profile = get_member_profile_impl("M006")
    assert "type_2_diabetes" in profile["health_flags"]
    assert "retinal_imaging_covered_in_full" in profile["special_coverage"]


def test_plan_details_merged_in():
    profile = get_member_profile_impl("M001")
    assert profile["plan_details"]["network"] == "VSP Signature (Premier Edge)"
