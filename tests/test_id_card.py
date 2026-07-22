from pathlib import Path

from app.tools.id_card import generate_id_card_pdf_impl


def test_sara_self_card():
    result = generate_id_card_pdf_impl("M001")
    assert result["holder"] == "Sara Kim"
    assert result["id_number"] == "VSP-0001-3841"
    assert Path(result["file_path"]).exists()
    assert Path(result["file_path"]).stat().st_size > 0


def test_sara_son_dependent_card():
    result = generate_id_card_pdf_impl("M001", dependent_name="Ethan")
    assert result["holder"] == "Ethan Kim"
    assert result["id_number"] == "VSP-0001-3841-01"
    assert Path(result["file_path"]).exists()


def test_unknown_dependent_returns_error():
    result = generate_id_card_pdf_impl("M001", dependent_name="Nobody")
    assert "error" in result


def test_unknown_member_returns_error():
    result = generate_id_card_pdf_impl("M999")
    assert "error" in result


def test_dependent_name_on_member_with_no_dependents_key_returns_error():
    """Maria (M002) has no "dependents" field in members.json at all --
    make sure that's handled as "not found", not a KeyError."""
    result = generate_id_card_pdf_impl("M002", dependent_name="Anyone")
    assert "error" in result
