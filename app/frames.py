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


def is_frame_request(text: str) -> bool:
    """Heuristic intent match for "suggest me some frames", kept narrow (an
    eyewear word plus a suggestion verb) so it doesn't hijack ordinary
    benefits questions that happen to mention "frames", e.g. "what's my
    frame allowance" -- those still go to the agent as before."""
    t = text.lower()
    mentions_eyewear = any(w in t for w in ("frame", "glasses", "eyewear", "spectacles"))
    asks_for_help = any(
        w in t
        for w in (
            "suggest",
            "recommend",
            "which frame",
            "help me pick",
            "help me choose",
            "suit",
            "best for my face",
            "face shape",
        )
    )
    return mentions_eyewear and asks_for_help


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
