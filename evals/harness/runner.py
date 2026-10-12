"""Runs eval cases through the real supervisor agent and records what happened.

Uses the same Runner + InMemorySessionService + {"member_id": ...} session
state as the Streamlit app (app/main.py), so evals exercise the production
code path. Tool calls are captured by a Runner plugin rather than by parsing
the event stream: AgentTool doesn't forward a specialist's inner events to the
supervisor's stream, but it *does* propagate the parent Runner's plugins to
the specialist's sub-Runner, so one plugin sees every call at every depth.

Call `configure_env()` before anything imports `app` -- `app.config` reads
VSP_DATA_DIR / VSP_GENERATED_DIR at import time.
"""

import asyncio
import contextvars
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from evals.paths import EVALS_DIR

SPECIALISTS = {
    "benefits_agent", "id_card_agent", "find_doctor_agent",
    "claims_agent", "billing_agent", "escalation_agent",
}

# One list per running case. asyncio tasks copy the context, and AgentTool
# awaits its sub-Runner inline, so every callback for a case lands here even
# with many cases running concurrently.
_current_trace: contextvars.ContextVar[Optional["CaseTrace"]] = contextvars.ContextVar("eval_trace", default=None)


@dataclass
class ToolCall:
    turn: int
    agent: str
    tool: str
    args: dict
    call_id: Optional[str] = None
    result: Any = None
    error: Optional[str] = None

    @property
    def is_specialist(self) -> bool:
        return self.tool in SPECIALISTS


@dataclass
class CaseTrace:
    case_id: str
    member_id: str
    turns: list[str]
    replies: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    latency_s: float = 0.0
    error: Optional[str] = None
    _turn: int = 0

    @property
    def final_reply(self) -> str:
        return self.replies[-1] if self.replies else ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("_turn")
        return d


def configure_env(data_dir: Path, generated_dir: Optional[Path] = None) -> None:
    os.environ["VSP_DATA_DIR"] = str(data_dir)
    os.environ["VSP_GENERATED_DIR"] = str(generated_dir or EVALS_DIR / ".generated")


def _make_recorder_plugin():
    from google.adk.plugins.base_plugin import BasePlugin

    class EvalRecorderPlugin(BasePlugin):
        def __init__(self):
            super().__init__(name="eval_recorder")

        async def before_tool_callback(self, *, tool, tool_args, tool_context):
            trace = _current_trace.get()
            if trace is not None:
                trace.tool_calls.append(ToolCall(
                    turn=trace._turn, agent=tool_context.agent_name, tool=tool.name,
                    args=dict(tool_args or {}), call_id=tool_context.function_call_id,
                ))
            return None

        async def after_tool_callback(self, *, tool, tool_args, tool_context, result):
            trace = _current_trace.get()
            if trace is not None:
                call = _find_call(trace, tool_context.function_call_id)
                if call is not None:
                    call.result = _jsonable(result)
            return None

        async def on_tool_error_callback(self, *, tool, tool_args, tool_context, error):
            trace = _current_trace.get()
            if trace is not None:
                call = _find_call(trace, tool_context.function_call_id)
                if call is not None:
                    call.error = repr(error)
            return None

        async def after_model_callback(self, *, callback_context, llm_response):
            trace = _current_trace.get()
            usage = getattr(llm_response, "usage_metadata", None)
            if trace is not None:
                trace.model_calls += 1
                if usage is not None:
                    trace.input_tokens += usage.prompt_token_count or 0
                    trace.output_tokens += usage.candidates_token_count or 0
            return None

    return EvalRecorderPlugin()


def _find_call(trace: CaseTrace, call_id: Optional[str]) -> Optional[ToolCall]:
    for call in reversed(trace.tool_calls):
        if call.call_id == call_id:
            return call
    return None


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def _event_text(event) -> str:
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None) or []
    return "".join(getattr(p, "text", None) or "" for p in parts)


def _final_text(events: list) -> str:
    # Same selection rule as app/main.py's _final_text, so we score exactly
    # what the member would see.
    for event in reversed(events):
        if getattr(event, "author", None) == "supervisor" and _event_text(event).strip():
            return _event_text(event)
    for event in reversed(events):
        if _event_text(event).strip():
            return _event_text(event)
    return ""


class AgentHarness:
    def __init__(self):
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService

        from app.agents.supervisor import root_agent
        from app.config import APP_NAME

        self.app_name = APP_NAME
        self.session_service = InMemorySessionService()
        self.runner = Runner(
            agent=root_agent,
            app_name=APP_NAME,
            session_service=self.session_service,
            plugins=[_make_recorder_plugin()],
        )

    async def run_case(self, case: dict, timeout_s: float = 180.0) -> CaseTrace:
        from google.genai import types

        trace = CaseTrace(case_id=case["id"], member_id=case["member_id"], turns=list(case["turns"]))
        _current_trace.set(trace)
        user_id = f"eval-{case['member_id']}"
        session_id = f"eval-{uuid.uuid4().hex[:12]}"
        await self.session_service.create_session(
            app_name=self.app_name, user_id=user_id, session_id=session_id,
            state={"member_id": case["member_id"]},
        )

        start = time.perf_counter()
        try:
            for i, text in enumerate(case["turns"]):
                trace._turn = i
                content = types.Content(role="user", parts=[types.Part(text=text)])

                async def _collect():
                    return [e async for e in self.runner.run_async(user_id=user_id, session_id=session_id, new_message=content)]

                events = await asyncio.wait_for(_collect(), timeout=timeout_s)
                trace.replies.append(_final_text(events))
        except Exception as exc:  # a crash is a scored failure, not a harness abort
            trace.error = f"{type(exc).__name__}: {exc}"
        finally:
            trace.latency_s = round(time.perf_counter() - start, 3)
        return trace
