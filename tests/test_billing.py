from app.tools.billing import get_billing_impl


def test_david_individual_plan_billing():
    result = get_billing_impl("M004")
    assert result["premium"] == 34.78
    assert result["autopay_day"] == 15
    assert result["last_payment_status"] == "successful"


def test_non_ip_member_returns_not_individual_plan_error():
    result = get_billing_impl("M001")
    assert result == {"error": "not individual plan"}


def test_unknown_member_returns_error():
    result = get_billing_impl("M999")
    assert "error" in result
