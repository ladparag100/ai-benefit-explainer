"""Google Cloud-native observability: Cloud Trace + Cloud Logging.

This deliberately builds spans and log entries from the ADK Runner's event
stream *after* each turn completes, rather than from LlmAgent's
before/after_agent and before/after_tool callback hooks. Reasoning: the
Runner/Event API is ADK's most fundamental, stable surface, while callback
hook signatures are more likely to have shifted between ADK versions. This
trades away live, in-flight spans (every sub-span in a turn ends up
clustered around the same "now" timestamp instead of reflecting real
historical timing) for something that is easy to keep working.

If you want true live per-agent/per-tool tracing as it happens, wire the
same trace_turn()/summarize_events() logic into LlmAgent's
before_agent_callback / after_agent_callback / before_tool_callback /
after_tool_callback instead -- check the current google-adk docs for exact
callback signatures before doing that, they were the least certain part of
this module at the time it was written.

Every external call in here (Cloud Trace export, Cloud Logging export) is
wrapped so a missing credential or a changed SDK shape degrades to local
stdlib logging instead of breaking the chat turn -- tracing must never be
allowed to take down the product it's observing.
"""

import logging
from dataclasses import dataclass
from typing import Any

from app.guardrails import redact_pii

logger = logging.getLogger("vsp.observability")

_configured = False
_tracer = None
_cloud_logger = None


def configure_observability() -> None:
    """Idempotent setup. Safe to call with no GCP credentials available --
    falls back to local-only logging so the app still runs on a laptop with
    no `gcloud auth` configured."""
    global _configured, _tracer, _cloud_logger
    if _configured:
        return
    _configured = True

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": "ai-benefit-explainer"}))
        provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("ai-benefit-explainer")
    except Exception:
        logger.warning("Cloud Trace export unavailable; continuing without it.", exc_info=True)
        _tracer = None

    try:
        import google.cloud.logging as cloud_logging

        client = cloud_logging.Client()
        _cloud_logger = client.logger("ai-benefit-explainer")
    except Exception:
        logger.warning("Cloud Logging export unavailable; falling back to local logs only.", exc_info=True)
        _cloud_logger = None


@dataclass
class ToolCallRecord:
    agent: str
    tool: str
    args: dict
    response: Any
    ok: bool


def summarize_events(events: list) -> list[ToolCallRecord]:
    """Walk an ADK Runner event stream -- flat across the whole supervisor +
    specialist invocation tree, each event tagged with its author -- and
    pull out every tool/specialist call in order, regardless of nesting
    depth. Returns [] rather than raising if the event shape doesn't match
    what this was written against."""
    calls: list[ToolCallRecord] = []
    try:
        pending_by_name: dict[str, dict] = {}
        for event in events:
            author = getattr(event, "author", "unknown")
            content = getattr(event, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                fn_call = getattr(part, "function_call", None)
                fn_response = getattr(part, "function_response", None)
                if fn_call is not None:
                    pending_by_name[fn_call.name] = {
                        "agent": author,
                        "args": dict(fn_call.args or {}),
                    }
                elif fn_response is not None:
                    pending = pending_by_name.pop(fn_response.name, {"agent": author, "args": {}})
                    response = fn_response.response
                    ok = not (isinstance(response, dict) and "error" in response)
                    calls.append(
                        ToolCallRecord(
                            agent=pending["agent"],
                            tool=fn_response.name,
                            args=pending["args"],
                            response=response,
                            ok=ok,
                        )
                    )
    except Exception:
        logger.warning("Failed to parse ADK event stream for tracing.", exc_info=True)
        return []
    return calls


def trace_turn(
    *,
    session_id: str,
    member_id: str,
    user_message: str,
    events: list,
    final_text: str,
    elapsed_ms: float,
) -> list[ToolCallRecord]:
    """Call once per completed chat turn. Emits one Cloud Trace span for the
    turn with one child span per tool/specialist call, plus a structured
    Cloud Logging entry (route decisions, tool calls, latency, errors, final
    response). Always returns the parsed tool-call records -- used by the
    Streamlit debug expander -- even if trace/log export isn't configured.
    """
    configure_observability()

    calls = summarize_events(events)

    if _tracer is not None:
        try:
            with _tracer.start_as_current_span("vsp.turn") as span:
                span.set_attribute("vsp.session_id", session_id)
                span.set_attribute("vsp.member_id", member_id)
                span.set_attribute("vsp.elapsed_ms", elapsed_ms)
                span.set_attribute("vsp.tool_call_count", len(calls))
                for call in calls:
                    with _tracer.start_as_current_span(f"vsp.tool.{call.tool}") as tool_span:
                        tool_span.set_attribute("vsp.agent", call.agent)
                        tool_span.set_attribute("vsp.ok", call.ok)
        except Exception:
            logger.warning("Failed to emit Cloud Trace span for turn.", exc_info=True)

    # Redacted before it ever reaches Cloud Logging -- member questions
    # routinely include their own name or contact info in free text, and
    # that shouldn't sit in plaintext in a Google-side log store.
    log_payload = {
        "session_id": session_id,
        "member_id": member_id,
        "user_message": redact_pii(user_message),
        "final_text": redact_pii(final_text),
        "elapsed_ms": elapsed_ms,
        "tool_calls": [{"agent": c.agent, "tool": c.tool, "args": c.args, "ok": c.ok} for c in calls],
    }
    if _cloud_logger is not None:
        try:
            _cloud_logger.log_struct(log_payload, severity="INFO")
        except Exception:
            logger.warning("Failed to write Cloud Logging entry for turn.", exc_info=True)
    else:
        logger.info("vsp.turn %s", log_payload)

    return calls
