"""Streamlit chat UI for the VSP Benefits Explainer.

Run with: streamlit run app/main.py
"""

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

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
from app.observability import trace_turn

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


async def _run_turn_async(runner, session_service, user_id, session_id, member_id, user_text) -> list:
    await _ensure_session(session_service, user_id, session_id, member_id)
    content = types.Content(role="user", parts=[types.Part(text=user_text)])
    events = []
    async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=content):
        events.append(event)
    return events


def run_turn(runner, session_service, user_id, session_id, member_id, user_text) -> list:
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


def _find_pdf_path(events: list) -> Optional[str]:
    """generate_id_card_pdf runs inside id_card_agent, which the supervisor
    calls via AgentTool -- AgentTool only merges the specialist's final text
    back up, so the tool's raw {"file_path": ...} return never reaches the
    supervisor's own event stream. It does, however, explicitly forward every
    nested event's state_delta up into the parent ToolContext.state, so
    app/tools/id_card.py stashes the path there instead (see that file for
    why). Scan events in reverse for the most recent one this turn."""
    for event in reversed(events):
        state_delta = getattr(getattr(event, "actions", None), "state_delta", None) or {}
        file_path = state_delta.get("temp:pdf_path")
        if file_path:
            return str(file_path)
    return None


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
    with st.chat_message(turn["role"]):
        st.markdown(turn["content"])
        if turn.get("pdf_path"):
            _render_download(turn["pdf_path"], key=f"dl-hist-{idx}")
        if turn.get("debug"):
            with st.expander("How this was answered"):
                st.write(turn["debug"])

user_text = st.chat_input(f"Ask a question as {member['name']}...")
if user_text:
    chat_history.append({"role": "user", "content": user_text})
    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        final_text = ""
        debug_info: dict = {}
        pdf_path = None
        with st.spinner("Thinking..."):
            start = time.time()
            try:
                events = run_turn(
                    runner, session_service, st.session_state.user_id, session_id, member_id, user_text
                )
                elapsed_ms = (time.time() - start) * 1000
                final_text = _final_text(events)
                tool_calls = trace_turn(
                    session_id=session_id,
                    member_id=member_id,
                    user_message=user_text,
                    events=events,
                    final_text=final_text,
                    elapsed_ms=elapsed_ms,
                )
                pdf_path = _find_pdf_path(events)
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
        {"role": "assistant", "content": final_text, "pdf_path": pdf_path, "debug": debug_info}
    )
