"""Streamlit chat UI for the VSP Benefits Explainer.

Run with: streamlit run app/main.py
"""

import asyncio
import json
import sys
import textwrap
import time
import uuid
from datetime import datetime
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
    frame_cost_breakdown,
    frame_image_path,
    get_frames_for_face_shape,
    is_frame_request,
    is_more_frames_request,
    recommend_frames,
)
from app.observability import trace_turn
from app.speech import transcribe_audio

st.set_page_config(page_title="VSP Benefits Explainer", page_icon="\U0001f453", layout="centered")


def _inject_style() -> None:
    """Loads the display/body typeface (the .streamlit/config.toml theme
    only sets the CSS font-family *name* -- the actual font file still has
    to come from somewhere) and a small CSS layer for the handful of things
    theme.toml can't reach: the hero banner, chat bubble spacing, and frame
    cards. Targets Streamlit's documented `data-testid` hooks rather than
    internal class names, since those are the stable, versioned-safe way to
    style built-in components.
    """
    # Two Markdown gotchas both matter here, or this silently renders as
    # visible text instead of being applied as HTML/CSS:
    # 1. textwrap.dedent -- a line indented 4+ spaces is a literal code
    #    block in Markdown, so this has to be dedented to column 0.
    # 2. No blank lines anywhere inside the HTML region -- Streamlit's
    #    unsafe_allow_html passthrough doesn't implement CommonMark's rule
    #    that a <style>/<script> block continues past blank lines; it ends
    #    the raw-HTML region at the first one, and everything after that
    #    point gets parsed as a new Markdown paragraph (and shown as text).
    st.markdown(
        textwrap.dedent(
            """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
        <style>
        html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', -apple-system, 'Segoe UI', sans-serif; }
        .block-container { max-width: 640px; padding-top: 1.6rem; padding-bottom: 1.5rem; }
        section[data-testid="stSidebar"] .block-container { padding-top: 1.6rem; }
        .vsp-hero {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            padding: 0.5rem 0.75rem;
            border-radius: 12px;
            background: var(--secondary-background-color);
            border: 1px solid var(--border-color, rgba(128,128,128,0.18));
            margin-bottom: 0.75rem;
        }
        .vsp-hero .vsp-icon { font-size: 1.25rem; line-height: 1; flex: none; }
        .vsp-hero h1 { font-size: 0.95rem; font-weight: 800; letter-spacing: -0.005em; margin: 0; line-height: 1.25; }
        .vsp-hero p { margin: 0; font-size: 0.72rem; opacity: 0.65; line-height: 1.2; }
        [data-testid="stChatMessage"] { border-radius: 14px; padding: 0.05rem 0.3rem; gap: 0.5rem; }
        [data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] { border-radius: 8px; width: 1.75rem; height: 1.75rem; }
        [data-testid="stChatMessage"] p { font-size: 0.92rem; margin-bottom: 0.4rem; }
        [data-testid="stButton"] button, [data-testid="stDownloadButton"] button { font-weight: 600; letter-spacing: 0.01em; padding: 0.3rem 0.9rem; font-size: 0.85rem; }
        [data-testid="stExpander"] { border-radius: 12px; font-size: 0.85rem; }
        [data-testid="stVerticalBlockBorderWrapper"] { transition: box-shadow 0.15s ease, transform 0.1s ease; }
        [data-testid="stVerticalBlockBorderWrapper"]:hover { box-shadow: 0 8px 20px rgba(18, 26, 36, 0.08); transform: translateY(-1px); }
        [data-testid="stImage"] img { border-radius: 10px; }
        @media (prefers-reduced-motion: reduce) {
            [data-testid="stVerticalBlockBorderWrapper"] { transition: none; }
        }
        </style>
        """
        ),
        unsafe_allow_html=True,
    )


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

    # generate_id_card_pdf (app/tools/id_card.py) and handoff_to_human
    # (app/tools/escalation.py) each stash their result in session state
    # rather than their return value -- see those files for why. Reading
    # from the session (rather than scanning the events above for it) and
    # popping means a stale value can't leak into a later, unrelated turn.
    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    pdf_path = session.state.pop("pdf_path", None)
    escalation_ticket = session.state.pop("escalation_ticket", None)

    return events, pdf_path, escalation_ticket


def run_turn(runner, session_service, user_id, session_id, member_id, user_text):
    return asyncio.run(
        _run_turn_async(runner, session_service, user_id, session_id, member_id, user_text)
    )


def _md_safe(text: str) -> str:
    """st.markdown/st.caption treat a matched pair of "$" as LaTeX math
    delimiters (documented behavior, via KaTeX) -- agent replies routinely
    contain several dollar amounts in one message (copays, allowances,
    frame prices), which accidentally opens/closes math mode and renders
    that stretch in KaTeX's font instead of the page's, often with broken
    output. Escaping every literal "$" keeps dollar amounts as plain text
    without touching intentional markdown like **bold** section headers."""
    return text.replace("$", "\\$")


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


def _render_frame_grid(frames: list, member: dict) -> None:
    columns = st.columns(len(frames))
    for column, frame in zip(columns, frames):
        with column, st.container(border=True):
            st.image(str(frame_image_path(frame)), use_container_width=True)
            st.markdown(f"**{frame['name']}**")
            st.caption(f"{frame['style']} · {frame['material']}")
            st.caption(_md_safe(f"${frame['price_usd']}"))
            breakdown = frame_cost_breakdown(frame, member)
            if not breakdown["eligible"]:
                st.caption(_md_safe(f"Frame allowance not available this period -- ${breakdown['out_of_pocket']} out of pocket"))
            elif breakdown["fully_covered"]:
                st.caption(_md_safe(f"Fully covered by your ${breakdown['allowance']} allowance"))
            else:
                st.caption(_md_safe(f"${breakdown['allowance']} allowance applied -- ${breakdown['out_of_pocket']} out of pocket"))
            st.caption(frame["description"])


def _render_frame_picker(turn: dict, key: str, member: dict) -> None:
    with st.chat_message("assistant"):
        st.markdown(_md_safe(turn["content"]))
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
            _render_frame_grid(matches, member)


def _render_more_frames(turn: dict, member: dict) -> None:
    with st.chat_message("assistant"):
        frames = get_frames_for_face_shape(turn["face_shape"])[turn["start"] : turn["end"]]
        st.markdown(
            f"**{len(frames)} more pick{'s' if len(frames) != 1 else ''} "
            f"for a {turn['face_shape'].lower()} face**"
        )
        _render_frame_grid(frames, member)
        total = len(get_frames_for_face_shape(turn["face_shape"]))
        if turn["end"] >= total:
            st.caption("That's the full catalog for this face shape.")


def _format_escalated_at(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return raw[:19].replace("T", " ") + " UTC"
    return dt.strftime("%b %-d, %Y at %-I:%M %p UTC")


def _render_escalation_callout(ticket: dict) -> None:
    reason = str(ticket.get("reason") or "unspecified").replace("_", " ").capitalize()
    ticket_id = ticket.get("ticket_id", "unknown")
    when = _format_escalated_at(str(ticket.get("escalated_at") or ""))

    # st.success renders in green, distinct from the neutral chat bubbles --
    # a deliberate visual cue that a handoff actually happened, not just
    # more chat text. "  \n" (two trailing spaces) is a markdown hard break,
    # so each field lands on its own line inside the one colored box.
    lines = [
        "**You're connected with a specialist** -- they'll follow up with full context, so you won't need to repeat anything.",
        f"**Ticket:** `{ticket_id}`",
        f"**Reason:** {reason}",
    ]
    if when:
        lines.append(f"**Logged:** {when}")
    st.success("  \n".join(lines), icon="🧑‍💼")


def _handle_user_message(
    chat_history: list,
    display_text: str,
    pipeline_text: str,
    *,
    member_id: str,
    member: dict,
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
        st.markdown(_md_safe(display_text))

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
                _render_more_frames(more_turn, member)
    elif is_frame_request(pipeline_text):
        # Deliberately not routed through the agent: a frame-shopping
        # question gets a deterministic catalog lookup driven by a radio
        # button, not an LLM call -- see app/frames.py.
        idx = len(chat_history)
        content = "Sure -- what's your face shape? I'll pull matching frames from our catalog and show what your " \
            f"${member['frame_allowance']} allowance covers:"
        turn = {"role": "assistant", "kind": "frame_picker", "content": content}
        chat_history.append(turn)
        _render_frame_picker(turn, key=f"faceshape-{member_id}-{generation}-{idx}", member=member)
    else:
        with st.chat_message("assistant"):
            final_text = ""
            debug_info: dict = {}
            pdf_path = None
            escalation_ticket = None
            with st.spinner("Thinking..."):
                start = time.time()
                try:
                    events, pdf_path, escalation_ticket = run_turn(
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

            st.markdown(_md_safe(final_text))
            if pdf_path:
                _render_download(pdf_path, key=f"dl-new-{len(chat_history)}")
            if escalation_ticket:
                _render_escalation_callout(escalation_ticket)
            with st.expander("How this was answered"):
                st.write(debug_info)

        chat_history.append(
            {
                "role": "assistant",
                "content": final_text,
                "pdf_path": pdf_path,
                "escalation_ticket": escalation_ticket,
                "debug": debug_info,
                "kind": "text",
            }
        )


MEMBERS = _load_members_for_ui()
MEMBER_IDS = list(MEMBERS.keys())

# Shown as quick-start buttons only before the first message of a
# conversation (see the empty-chat_history check below) -- one per
# specialist that's demoable without extra member-specific setup, so a new
# user can "lean in" instead of facing a blank input box.
SUGGESTED_PROMPTS = [
    "Can I get my ID card?",
    "Am I due for new glasses?",
    "Find a doctor near me",
    "What's the status of my last claim?",
    "When's my next payment due?",
]

_inject_style()
st.markdown(
    textwrap.dedent(
        """
    <div class="vsp-hero">
        <div class="vsp-icon">\U0001f453</div>
        <div>
            <h1>VSP Benefits Explainer</h1>
            <p>Multi-agent prototype &middot; Google ADK supervisor + specialists &middot; Gemini on Vertex AI</p>
        </div>
    </div>
    """
    ),
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("Member")
    member_id = st.selectbox(
        "Viewing as",
        MEMBER_IDS,
        format_func=lambda mid: f"{MEMBERS[mid]['name']} -- {MEMBERS[mid]['plan']}",
    )
    member = MEMBERS[member_id]

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
        _render_frame_picker(turn, key=f"faceshape-{member_id}-{generation}-{idx}", member=member)
        continue
    if turn.get("kind") == "frame_more":
        _render_more_frames(turn, member)
        continue
    with st.chat_message(turn["role"]):
        st.markdown(_md_safe(turn["content"]))
        if turn.get("pdf_path"):
            _render_download(turn["pdf_path"], key=f"dl-hist-{idx}")
        if turn.get("escalation_ticket"):
            _render_escalation_callout(turn["escalation_ticket"])
        if turn.get("debug"):
            with st.expander("How this was answered"):
                st.write(turn["debug"])

if not chat_history:
    st.caption("Try asking:")
    prompt_cols = st.columns(len(SUGGESTED_PROMPTS))
    for i, suggested_text in enumerate(SUGGESTED_PROMPTS):
        with prompt_cols[i]:
            if st.button(suggested_text, key=f"suggested-{member_id}-{generation}-{i}", use_container_width=True):
                _handle_user_message(
                    chat_history,
                    suggested_text,
                    suggested_text,
                    member_id=member_id,
                    member=member,
                    generation=generation,
                    session_id=session_id,
                    runner=runner,
                    session_service=session_service,
                )

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
                st.error(_md_safe(f"Voice transcription failed: {type(exc).__name__}: {exc}"))
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
                    member=member,
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
            member=member,
            generation=generation,
            session_id=session_id,
            runner=runner,
            session_service=session_service,
        )
