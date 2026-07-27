import pytest

from app.frames import (
    FACE_SHAPES,
    RECOMMENDATION_LIMIT,
    frame_image_path,
    get_frames_for_face_shape,
    is_frame_request,
    is_more_frames_request,
    recommend_frames,
)


def test_every_face_shape_has_matches():
    for shape in FACE_SHAPES:
        matches = get_frames_for_face_shape(shape)
        assert matches, f"no frames recommended for {shape}"


def test_lookup_is_case_insensitive():
    assert get_frames_for_face_shape("round") == get_frames_for_face_shape("Round")


def test_unknown_face_shape_returns_empty():
    assert get_frames_for_face_shape("hexagonal") == []


def test_every_frame_image_exists_on_disk():
    for shape in FACE_SHAPES:
        for frame in get_frames_for_face_shape(shape):
            assert frame_image_path(frame).exists(), frame["image"]


def test_recommend_frames_capped_at_three():
    for shape in FACE_SHAPES:
        assert len(recommend_frames(shape)) == RECOMMENDATION_LIMIT
        assert recommend_frames(shape) == get_frames_for_face_shape(shape)[:RECOMMENDATION_LIMIT]


def test_every_frame_has_price_in_expected_range():
    for shape in FACE_SHAPES:
        for frame in get_frames_for_face_shape(shape):
            assert 70 <= frame["price_usd"] <= 400


@pytest.mark.parametrize(
    "text",
    [
        "Can you suggest some frames for me?",
        "What frames would suit my face?",
        "Recommend glasses for my face shape",
        "Help me pick frames",
        "Which frame style suits a round face?",
    ],
)
def test_frame_shopping_questions_are_detected(text):
    assert is_frame_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "What's my frame allowance this year?",
        "How much is my frame reimbursement?",
        "Can I get my ID card?",
        "What's my copay for exams?",
        "I need new glasses, how much does my plan cover?",
    ],
)
def test_benefits_questions_are_not_misdetected(text):
    assert is_frame_request(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Show me more frames",
        "Any other options?",
        "Do you have other options",
        "Got any different ones?",
        "Show me 3 more frames",
        "more glasses please",
    ],
)
def test_more_frames_requests_are_detected(text):
    assert is_more_frames_request(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "Can you suggest some frames for me?",
        "What's my frame allowance this year?",
        "Can I get my ID card?",
    ],
)
def test_unrelated_questions_are_not_more_frames_requests(text):
    assert is_more_frames_request(text) is False
