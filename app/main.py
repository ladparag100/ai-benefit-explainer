"""Streamlit chat UI for the VSP Benefits Explainer.

Run with: streamlit run app/main.py
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

# `streamlit run app/main.py` puts this file's own directory (app/) on
# sys.path, not the repo root -- so the `app` package itself isn't
# importable unless the repo root is added first. Do this before any
# `app.*` import, regardless of cwd or PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Must be the first `app.*` import, and must come before streamlit/
# google.adk/google.genai below -- app.config sets
# PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION as a side effect, and that only
# works if it runs before anything in the process first touches protobuf
# (chromadb, but also transitively google.adk/google.genai). Once some
# other import initializes protobuf's C++ implementation, setting the env
# var afterward is too late.
import app.config  # noqa: F401

import streamlit as st
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.agent import root_agent
from app.config import APP_NAME, DATA_DIR
from app.frames import (
    FACE_SHAPES,
    RECOMMENDATION_LIMIT,
    frame_image_path,
    get_frames_for_face_shape,
    is_frame_request,
    is_more_frames_request,
    recommend_frames,
)
from app.observability import trace_turn
from app.speech import transcribe_audio

st.set_page_config(page_title="VSP Benefits Explainer", page_icon="\U0001f453", layout="centered")


@st.cache_resource
def _get_runner_and_sessions():
    session_service = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=session_service)
    return runner, session_service


@st.cache_data
def _load_members_for_ui() -> dict:
    with open(DATA_DIR / "members.json") as f:
        return json.load(f)


async def _ensure_session(session_service, user_id: str, session_id: str, member_id: str) -> None:
    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    if session is None:
        await session_service.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
            state={"member_id": member_id},
        )


async def _run_turn_async(runner, session_service, user_id, session_id, member_id, user_text):
    await _ensure_session(session_service, user_id, session_id, member_id)
    content = types.Content(role="user", parts=[types.Part(text=user_text)])
    events = []
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        events.append(event)

    # generate_id_card_pdf (app/tools/id_card.py) stashes the PDF path in
    # session state rather than its return value -- see that file for why,
    # and for why it's a plain key rather than "temp:"-prefixed. Reading it
    # from the session (rather than scanning the events above for it) and
    # popping it means a stale path can't leak into a later, unrelated turn
    # that never calls generate_id_card_pdf.
    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    pdf_path = session.state.pop("pdf_path", None)

    return events, pdf_path


def run_turn(runner, session_service, user_id, session_id, member_id, user_text):
    return asyncio.run(
        _run_turn_async(runner, session_service, user_id, session_id, member_id, user_text)
    )


def _event_text(event) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(getattr(p, "text", None) or "" for p in parts)


def _final_text(events: list) -> str:
    for event in reversed(events):
        if getattr(event, "author", None) == "supervisor" and _event_text(event).strip():
            return _event_text(event)
    for event in reversed(events):
        if _event_text(event).strip():
            return _event_text(event)
    return "Sorry, I couldn't put together a response that time -- please try asking again."


def _render_download(pdf_path: str, key: str) -> None:
    path = Path(pdf_path)
    if not path.exists():
        st.warning("A PDF was reported but couldn't be found on disk.")
        return
    st.download_button(
        "Download ID card PDF",
        data=path.read_bytes(),
        file_name=path.name,
        mime="application/pdf",
        key=key,
    )


def _render_frame_grid(frames: list) -> None:
    columns = st.columns(len(frames))
    for column, frame in zip(columns, frames):
        with column:
            st.image(str(frame_image_path(frame)), use_container_width=True)
            st.markdown(f"**{frame['name']}**")
            st.caption(f"{frame['style']} · {frame['material']}")
            st.caption(f"${frame['price_usd']}")
            st.caption(frame["description"])


def _render_frame_picker(turn: dict, key: str) -> None:
    with st.chat_message("assistant"):
        st.markdown(turn["content"])
        face_shape = st.radio(
            "Face shape",
            FACE_SHAPES,
            index=None,
            horizontal=True,
            label_visibility="collapsed",
            key=key,
        )
        if face_shape:
            # Recorded on the turn itself (not just the widget) so a later
            # "show me more" in the chat can find this as the active
            # recommendation and knows where pagination left off.
            turn["face_shape"] = face_shape
            turn.setdefault("shown_count", RECOMMENDATION_LIMIT)
            matches = recommend_frames(face_shape)
            st.markdown(f"**Top {len(matches)} picks for a {face_shape.lower()} face**")
            _render_frame_grid(matches)


def _render_more_frames(turn: dict) -> None:
    with st.chat_message("assistant"):
        frames = get_frames_for_face_shape(turn["face_shape"])[turn["start"] : turn["end"]]
        st.markdown(
            f"**{len(frames)} more pick{'s' if len(frames) != 1 else ''} "
            f"for a {turn['face_shape'].lower()} face**"
        )
        _render_frame_grid(frames)
        total = len(get_frames_for_face_shape(turn["face_shape"]))
        if turn["end"] >= total:
            st.caption("That's the full catalog for this face shape.")


def _handle_user_message(
    chat_history: list,
    display_text: str,
    pipeline_text: str,
    *,
    member_id: str,
    generation: int,
    session_id: str,
    runner,
    session_service,
) -> None:
    """Handle one new turn, whichever way it arrived (typed or transcribed
    from voice). display_text is what's echoed as the user's chat bubble;
    pipeline_text is what drives intent detection and the agent -- for a
    voice message these can differ (see app/speech.py)."""
    chat_history.append({"role": "user", "content": display_text, "kind": "text"})
    with st.chat_message("user"):
        st.markdown(display_text)

    if is_more_frames_request(pipeline_text):
        # Continue pagination on the most recently active frame_picker turn
        # (the last one where a face shape was actually chosen), rather than
        # starting a new recommendation from scratch.
        active = next(
            (t for t in reversed(chat_history) if t.get("kind") == "frame_picker" and t.get("face_shape")),
            None,
        )
        if active is None:
            reply = (
                "I don't have an active frame recommendation yet -- ask me to "
                "suggest some frames and pick your face shape first."
            )
            chat_history.append({"role": "assistant", "content": reply, "kind": "text"})
            with st.chat_message("assistant"):
                st.markdown(reply)
        else:
            shape = active["face_shape"]
            total_matches = get_frames_for_face_shape(shape)
            already_shown = active.get("shown_count", RECOMMENDATION_LIMIT)
            if already_shown >= len(total_matches):
                reply = (
                    f"We only have these {len(total_matches)} frames for a "
                    f"{shape.lower()} face -- you've already seen them all."
                )
                chat_history.append({"role": "assistant", "content": reply, "kind": "text"})
                with st.chat_message("assistant"):
                    st.markdown(reply)
            else:
                new_shown = min(already_shown + RECOMMENDATION_LIMIT, len(total_matches))
                active["shown_count"] = new_shown
                more_turn = {
                    "role": "assistant",
                    "kind": "frame_more",
                    "face_shape": shape,
                    "start": already_shown,
                    "end": new_shown,
                }
                chat_history.append(more_turn)
                _render_more_frames(more_turn)
    elif is_frame_request(pipeline_text):
        # Deliberately not routed through the agent: a frame-shopping
        # question gets a deterministic catalog lookup driven by a radio
        # button, not an LLM call -- see app/frames.py.
        idx = len(chat_history)
        content = "Sure -- what's your face shape? I'll pull matching frames from our catalog:"
        turn = {"role": "assistant", "kind": "frame_picker", "content": content}
        chat_history.append(turn)
        _render_frame_picker(turn, key=f"faceshape-{member_id}-{generation}-{idx}")
    else:
        with st.chat_message("assistant"):
            final_text = ""
            debug_info: dict = {}
            pdf_path = None
            with st.spinner("Thinking..."):
                start = time.time()
                try:
                    events, pdf_path = run_turn(
                        runner, session_service, st.session_state.user_id, session_id, member_id, pipeline_text
                    )
                    elapsed_ms = (time.time() - start) * 1000
                    final_text = _final_text(events)
                    tool_calls = trace_turn(
                        session_id=session_id,
                        member_id=member_id,
                        user_message=pipeline_text,
                        events=events,
                        final_text=final_text,
                        elapsed_ms=elapsed_ms,
                    )
                    debug_info = {
                        "elapsed_ms": round(elapsed_ms, 1),
                        "routed_calls": [
                            {"agent": c.agent, "tool": c.tool, "ok": c.ok, "args": c.args}
                            for c in tool_calls
                        ],
                    }
                except Exception as exc:  # noqa: BLE001 -- surface any failure to the chat, don't crash the app
                    final_text = (
                        "Something went wrong reaching the agents -- this usually means "
                        "GOOGLE_CLOUD_PROJECT / Vertex AI credentials aren't configured in "
                        "this environment yet. Details for debugging:\n\n"
                        f"`{type(exc).__name__}: {exc}`"
                    )
                    debug_info = {"error": f"{type(exc).__name__}: {exc}"}

            st.markdown(final_text)
            if pdf_path:
                _render_download(pdf_path, key=f"dl-new-{len(chat_history)}")
            with st.expander("How this was answered"):
                st.write(debug_info)

        chat_history.append(
            {
                "role": "assistant",
                "content": final_text,
                "pdf_path": pdf_path,
                "debug": debug_info,
                "kind": "text",
            }
        )


MEMBERS = _load_members_for_ui()
MEMBER_IDS = list(MEMBERS.keys())

st.title("\U0001f453 VSP Benefits Explainer")
st.caption("Multi-agent prototype -- Google ADK supervisor + specialists, Gemini on Vertex AI")

with st.sidebar:
    st.header("Member")
    member_id = st.selectbox(
        "Viewing as",
        MEMBER_IDS,
        format_func=lambda mid: f"{MEMBERS[mid]['name']} -- {MEMBERS[mid]['plan']}",
    )
    member = MEMBERS[member_id]
    st.caption(f"{member['coverage_type']} · effective {member['effective_date']}")
    if member.get("situation"):
        st.caption(f"Situation: {member['situation']}")

    if st.button("Clear this member's conversation"):
        st.session_state.setdefault("chats", {})[member_id] = []
        st.session_state.setdefault("session_gen", {})[member_id] = (
            st.session_state.get("session_gen", {}).get(member_id, 0) + 1
        )
        st.rerun()

if "chats" not in st.session_state:
    st.session_state.chats = {}
if "session_gen" not in st.session_state:
    st.session_state.session_gen = {}
if "user_id" not in st.session_state:
    st.session_state.user_id = f"demo-{uuid.uuid4().hex[:8]}"

chat_history = st.session_state.chats.setdefault(member_id, [])
generation = st.session_state.session_gen.get(member_id, 0)
session_id = f"session-{member_id}-{generation}"

runner, session_service = _get_runner_and_sessions()

for idx, turn in enumerate(chat_history):
    if turn.get("kind") == "frame_picker":
        _render_frame_picker(turn, key=f"faceshape-{member_id}-{generation}-{idx}")
        continue
    if turn.get("kind") == "frame_more":
        _render_more_frames(turn)
        continue
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        if turn.get("pdf_path"):
            _render_download(turn["pdf_path"], key=f"dl-hist-{idx}")
        if turn.get("debug"):
            with st.expander("How this was answered"):
                st.write(turn["debug"])

# accept_audio=True puts a mic icon directly inside the chat input box
# itself (not a separate control above it) -- recording and submitting
# returns a dict-like object with `.text` and `.audio` instead of a plain
# string. Behaves like a normal chat_input submission either way: one-shot,
# resets after use, no manual dedup needed across reruns.
submission = st.chat_input(
    f"Ask a question as {member['name']}...",
    accept_audio=True,
    audio_sample_rate=16000,
)

if submission:
    audio_file = submission.audio
    if audio_file is not None:
        with st.spinner("Transcribing your voice message..."):
            try:
                transcript = transcribe_audio(audio_file.getvalue(), getattr(audio_file, "type", None) or "audio/wav")
            except Exception as exc:  # noqa: BLE001 -- surface transcription failures without crashing the app
                transcript = None
                st.error(f"Voice transcription failed: {type(exc).__name__}: {exc}")
        if transcript is not None:
            if transcript.is_empty:
                st.warning("Sorry, I couldn't make out any speech in that recording -- please try again.")
            else:
                # original_text is what's echoed as "what you said"; english_text
                # (auto-detected + translated in the same Gemini call) drives
                # intent detection and the agent, since both are English-based.
                display_text = transcript.original_text or transcript.english_text
                pipeline_text = transcript.english_text or transcript.original_text
                _handle_user_message(
                    chat_history,
                    display_text,
                    pipeline_text,
                    member_id=member_id,
                    generation=generation,
                    session_id=session_id,
                    runner=runner,
                    session_service=session_service,
                )
    elif submission.text:
        _handle_user_message(
            chat_history,
            submission.text,
            submission.text,
            member_id=member_id,
            generation=generation,
            session_id=session_id,
            runner=runner,
            session_service=session_service,
        )
