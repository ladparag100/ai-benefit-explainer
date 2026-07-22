"""Re-export for `adk web` / `adk run` CLI auto-discovery, which looks for a
module-level `root_agent` in an `agent.py` at the agent package root.

Kept separate from app/__init__.py on purpose: importing app.tools.* for
unit tests should never eagerly pull in ADK's agent graph (and the
GOOGLE_CLOUD_PROJECT / Vertex AI credentials that implies) just because
`app` was imported.
"""

from app.agents.supervisor import root_agent

__all__ = ["root_agent"]
