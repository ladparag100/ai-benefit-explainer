"""Frame recommendations by face shape.

Pure data lookup, deliberately not an ADK tool: the Streamlit UI collects the
face shape directly from a radio button and renders matches itself, with no
LLM call in the loop.
"""

import json
from functools import lru_cache
from typing import Any

from app.config import DATA_DIR, FRAMES_DIR

FACE_SHAPES = ["Oval", "Round", "Square", "Heart", "Diamond", "Oblong"]

RECOMMENDATION_LIMIT = 3


@lru_cache(maxsize=1)
def _load_frames() -> list[dict[str, Any]]:
    with open(DATA_DIR / "frames.json") as f:
        return json.load(f)


def get_frames_for_face_shape(face_shape: str) -> list[dict[str, Any]]:
    shape = face_shape.strip().lower()
    return [f for f in _load_frames() if shape in f["face_shapes"]]


def recommend_frames(face_shape: str, limit: int = RECOMMENDATION_LIMIT) -> list[dict[str, Any]]:
    """The subset of get_frames_for_face_shape actually shown to the member --
    capped so a chat reply stays a quick pick, not a full catalog browse."""
    return get_frames_for_face_shape(face_shape)[:limit]


def frame_image_path(frame: dict[str, Any]):
    return FRAMES_DIR / frame["image"]


def frame_cost_breakdown(frame: dict[str, Any], member: dict[str, Any]) -> dict[str, Any]:
    """How much of a frame's price the member's plan actually covers right
    now, given their real frame_allowance and whether they're still
    eligible for it this benefit period. Eligibility can be false either
    because the full allowance was already used this period ("self": true)
    or because a plan rule blocks it -- e.g. Priya Patel (M005) already
    used contacts, and VSP plans cover contacts or frames, not both, per
    benefit period (see app/tools/members.py / the qa_response_patterns
    knowledge doc for the same rule as the benefits agent applies)."""
    allowance_used = member.get("frame_allowance_used", {})
    eligible = allowance_used.get("eligible_this_year", True) and allowance_used.get("self") is not True
    allowance = member.get("frame_allowance", 0) if eligible else 0
    price = frame["price_usd"]
    out_of_pocket = max(0, price - allowance)
    return {
        "eligible": eligible,
        "allowance": allowance,
        "price": price,
        "out_of_pocket": out_of_pocket,
        "fully_covered": eligible and out_of_pocket == 0,
    }


_EYEWEAR_WORDS = ("frame", "glasses", "eyewear", "spectacles")

# Unambiguous: asking for a recommendation can't be mistaken for a benefits
# question, so these trigger regardless of anything else in the message.
_RECOMMENDATION_PHRASES = (
    "suggest",
    "recommend",
    "which frame",
    "help me pick",
    "help me choose",
    "suit",
    "best for my face",
    "face shape",
)

# Ambiguous on their own -- "show"/"see"/"browse" plus an eyewear word could
# just as easily mean "show me my frame allowance". Only treated as a
# browse-the-catalog request when none of _BENEFITS_CONTEXT_WORDS is also
# present, so real benefits questions still go to the agent as before.
_BROWSE_WORDS = ("show", "see", "browse", "get")
_BENEFITS_CONTEXT_WORDS = (
    "allowance",
    "benefit",
    "coverage",
    "cover",
    "copay",
    "reimbursement",
    "cost",
    "price",
    "network",
    "provider",
    "doctor",
    "plan",
    "claim",
)


def is_frame_request(text: str) -> bool:
    """Heuristic intent match for a frame-shopping question -- either asking
    for a recommendation ("suggest me some frames") or just asking to browse
    ("show me some frames", "show frames"). Kept narrow so it doesn't hijack
    ordinary benefits questions that happen to mention "frames", e.g.
    "what's my frame allowance" -- those still go to the agent as before."""
    t = text.lower()
    if not any(w in t for w in _EYEWEAR_WORDS):
        return False
    if any(phrase in t for phrase in _RECOMMENDATION_PHRASES):
        return True
    if any(w in t for w in _BROWSE_WORDS) and not any(w in t for w in _BENEFITS_CONTEXT_WORDS):
        return True
    return False


def is_more_frames_request(text: str) -> bool:
    """Heuristic intent match for continuing a frame recommendation ("show
    me more", "any other options"). Checked before is_frame_request in
    app/main.py so a phrase like "show me more frames that would suit me"
    (which also matches is_frame_request's "suit") is treated as a
    continuation of the existing pick, not a request to start over."""
    t = text.lower()
    return any(
        phrase in t
        for phrase in (
            "more frame",
            "more glasses",
            "more option",
            "more choice",
            "more suggestion",
            "show more",
            "any other",
            "other option",
            "another option",
            "different one",
            "different frame",
        )
    )
