from app.tools.escalation import handoff_to_human_impl


def test_handoff_returns_ticket_and_context():
    result = handoff_to_human_impl("M001", "member_requested_human", "Wants to speak to a person about a billing dispute.")
    assert result["status"] == "escalated"
    assert result["ticket_id"].startswith("ESC-")
    assert result["member_id"] == "M001"
    assert result["reason"] == "member_requested_human"
    assert "escalated_at" in result


def test_handoff_ticket_ids_are_unique():
    a = handoff_to_human_impl("M001", "low_confidence", "test")
    b = handoff_to_human_impl("M001", "low_confidence", "test")
    assert a["ticket_id"] != b["ticket_id"]
