from app.tools.claims import get_claims_impl


def test_robert_has_two_claims_including_retinal_imaging():
    result = get_claims_impl("M006")
    assert len(result["claims"]) == 2
    services = [c["service"] for c in result["claims"]]
    assert any("retinal imaging" in s for s in services)


def test_james_new_member_has_no_claims():
    result = get_claims_impl("M003")
    assert result["claims"] == []


def test_david_oon_reimbursement_claim():
    result = get_claims_impl("M004")
    assert len(result["claims"]) == 1
    assert result["claims"][0]["status"] == "Processed (OON reimbursement)"
