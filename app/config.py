"""Shared paths and model configuration for the VSP Benefits Explainer.

Every value here is overridable via environment variable so the same code
runs unchanged locally, in Cloud Shell, and on Cloud Run.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent
REPO_ROOT = APP_DIR.parent

# Load repo-root .env (git-ignored) for local dev, e.g. GOOGLE_API_KEY /
# GOOGLE_GENAI_USE_VERTEXAI -- never overrides a var already set in the
# real shell environment (e.g. on Cloud Run). NOTE: for `streamlit run`,
# this is too late to affect PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION below --
# see run.sh, which sources .env before the streamlit process even starts.
load_dotenv(REPO_ROOT / ".env")

# chromadb bundles its own OTLP/gRPC exporter, compiled against a protobuf
# generated-code layout that the newer protobuf runtime (pulled in
# transitively by google-genai / google-cloud-trace / google-cloud-logging)
# refuses to load via its C++ implementation ("Descriptors cannot be
# created directly"). Forcing the pure-Python protobuf implementation is
# the standard workaround and must be set before the first `import
# chromadb` anywhere in the process -- this module is imported first by
# every entry point, so it's set here as the single source of truth.
#
# Important caveat: under `streamlit run`, Streamlit's own CLI bootstrap
# imports protobuf-based modules before this module ever runs, which locks
# in the C++ implementation regardless of what's set here. run.sh handles
# that case by exporting this var into the shell environment before
# launching streamlit at all.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

DATA_DIR = APP_DIR / "data"
KNOWLEDGE_DIR = APP_DIR / "rag" / "knowledge"
PROMPTS_DIR = APP_DIR / "prompts"

CHROMA_DIR = Path(os.environ.get("VSP_CHROMA_DIR", str(REPO_ROOT / "chroma_store")))
CHROMA_COLLECTION = "vsp_knowledge"

GENERATED_DIR = Path(os.environ.get("VSP_GENERATED_DIR", str(APP_DIR / "generated")))

GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")

# Pinned Gemini versions go stale fast (e.g. gemini-2.5-flash was retired for
# new API-key users within months). Default to Google's rolling "-latest"
# aliases instead, which point at whatever current model replaces them.
# Both default to the flash tier, not pro -- the free Gemini Developer API
# tier gives Pro-tier models (gemini-pro-latest) zero quota, while Flash
# models are actually usable on it. Override via env var (e.g. to
# gemini-pro-latest) if you're on a paid tier and want stronger routing.
SUPERVISOR_MODEL = os.environ.get("VSP_SUPERVISOR_MODEL", "gemini-flash-latest")
SPECIALIST_MODEL = os.environ.get("VSP_SPECIALIST_MODEL", "gemini-flash-latest")
EMBEDDING_MODEL = os.environ.get("VSP_EMBEDDING_MODEL", "gemini-embedding-001")

APP_NAME = "vsp-benefits-explainer"
