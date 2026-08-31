# AI Benefit Explainer

A multi-agent, Google-first prototype for the VSP AI-assisted benefits
explainer hackathon. A supervisor agent routes each member question to one
of six specialists, built entirely on **Google ADK** + **Gemini on Vertex
AI**, grounded with a small **RAG** knowledge base, and observed through
**Cloud Trace + Cloud Logging** (no third-party tracing service).

## Architecture

- **Supervisor** (`app/agents/supervisor.py`) -- a Google ADK `Agent`
  whose `tools` list contains all six specialists wrapped in `AgentTool`.
  This keeps the supervisor in control: each specialist runs to
  completion and returns a factual summary as a tool result, and the
  supervisor composes the member-facing reply itself, in the four-beat
  format (Interpret internally, then **Answer / Plan details / Next
  step**, or escalate). This is deliberately *not* ADK's
  `sub_agents=[...]` auto-transfer pattern, which would hand full
  conversation control to whichever specialist gets picked.
- **Six specialists**: `benefits_agent`, `id_card_agent`,
  `find_doctor_agent`, `claims_agent`, `billing_agent`,
  `escalation_agent` -- each a narrow `Agent` with one or two tools and a
  tight instruction.
- **Tools** (`app/tools/`) read the mock JSON in `app/data/` directly.
  Every tool that needs to know "which member" pulls `member_id` from
  ADK session state via `ToolContext`, rather than trusting the model to
  supply it -- the model can't hallucinate a wrong member.
- **RAG** (`app/rag/`): four markdown files chunked and embedded via a
  Vertex AI embedding model, stored in a local ChromaDB
  `PersistentClient`. Only plan rules / common features / worked examples
  / escalation & tone guidance live here -- never member-specific data
  (that's always a tool call, so it can't go stale or leak across
  members).
- **Observability** (`app/observability.py`): builds Cloud Trace spans and
  a structured Cloud Logging entry from the ADK `Runner`'s event stream
  after each turn -- see the module docstring for why this reads events
  after the fact rather than hooking ADK's `before/after_*` callbacks.
- **UI** (`app/main.py`): Streamlit, sidebar member picker, chat, PDF
  download button, and a "How this was answered" expander per turn
  showing the routed specialist(s), tool calls, and latency.

## One-time verification before you rely on this

This was generated against my best knowledge of `google-adk` /
`google-genai` APIs, which move quickly. Two things to double check the
first time you run it:

1. **Model IDs.** `app/config.py` defaults to `gemini-2.5-pro` /
   `gemini-2.5-flash` / `text-embedding-004`. Check Vertex AI Model Garden
   for what's current and override via `VSP_SUPERVISOR_MODEL` /
   `VSP_SPECIALIST_MODEL` / `VSP_EMBEDDING_MODEL` env vars if needed --
   don't edit the code.
2. **`embed_texts()` response shape** in `app/rag/build_index.py` is the
   single most likely thing to need a tweak against your installed
   `google-genai` version -- it raises a clear error rather than failing
   silently if the shape doesn't match.

## Local setup

```bash
cd ai-benefit-explainer
python3 -m venv .venv && source .venv/bin/activate
pip install -U -r requirements.txt

gcloud auth application-default login
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=us-central1
export GOOGLE_GENAI_USE_VERTEXAI=TRUE

# Enable the APIs this uses, once per project:
gcloud services enable aiplatform.googleapis.com cloudtrace.googleapis.com \
    logging.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
    --project "$GOOGLE_CLOUD_PROJECT"

# Build the RAG index (also happens automatically on first query if you skip this)
python -m app.rag.build_index

streamlit run app/main.py
```

### Fast agent-only iteration

Before wiring up the Streamlit UI, `google-adk` ships a local dev UI for
poking at the agent graph directly:

```bash
adk web
```

Run from the repo root; it should auto-discover `app/agent.py`'s
`root_agent`. If auto-discovery doesn't find it, check the current ADK CLI
docs for the expected package layout -- this convention is one of the
more version-sensitive parts of ADK's CLI. The Streamlit app doesn't
depend on this working; it's purely a dev-speed shortcut.

## Testing

```bash
pytest
```

All tests exercise the pure `_impl` functions in `app/tools/*.py`
directly (explicit `member_id`, no `ToolContext`/ADK needed) plus the
offline chunking logic in `app/rag/build_index.py`. None of them need
GCP credentials or network access -- nothing calls Gemini, embeddings, or
Chroma's query path in the test suite. Covers: Sara's dependent ID card,
Priya's contacts-used-blocks-frames branch, David's IP billing, Robert's
retinal imaging coverage, James's no-claims new-member case, and Maria's
due-for-glasses facts.

## Deploying to Cloud Run

```bash
gcloud run deploy vsp-explainer \
  --source . \
  --region us-central1 \
  --project "$GOOGLE_CLOUD_PROJECT" \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=us-central1
```

Grant the Cloud Run service's runtime service account these roles so it
can call Vertex AI and write traces/logs -- staying fully within Google
Cloud like this means **no Secret Manager entries are needed**, auth
flows entirely through the attached service account:

```bash
SA="$(gcloud run services describe vsp-explainer --region us-central1 --format='value(spec.template.spec.serviceAccountName)')"
for role in roles/aiplatform.user roles/cloudtrace.agent roles/logging.logWriter; do
  gcloud projects add-iam-policy-binding "$GOOGLE_CLOUD_PROJECT" \
    --member="serviceAccount:${SA}" --role="$role"
done
```

**RAG index on Cloud Run**: `query_knowledge` builds the index itself on
first use if the Chroma collection is empty, so the app works out of the
box. Because Cloud Run instances are ephemeral and can scale beyond one,
each cold-started instance indexes independently the first time it's
queried -- fine for a demo, but for consistency across instances in a
real deployment, run `python -m app.rag.build_index` once against a
shared/persistent `VSP_CHROMA_DIR`, or bake it into your own build step.

**Session storage**: `InMemorySessionService` is process-local, so
conversation history doesn't survive a Cloud Run instance being
recycled or a request landing on a different instance. Fine for a
3-minute demo; swap in `DatabaseSessionService` (or a Vertex AI-backed
session service, if available in your ADK version) before this needs to
survive real traffic.

## Cloud Shell workflow

This was scaffolded locally. To continue from Cloud Shell Editor (which
comes with `gcloud` already authenticated to your account):

```bash
git clone <your-repo-url>
cd ai-benefit-explainer
python3 -m venv .venv && source .venv/bin/activate
pip install -U -r requirements.txt
gcloud config set project your-project-id
export GOOGLE_CLOUD_PROJECT=your-project-id GOOGLE_GENAI_USE_VERTEXAI=TRUE
python -m app.rag.build_index
streamlit run app/main.py --server.port 8080
```

Cloud Shell will offer to preview port 8080 in the browser.

## Repo layout

```
app/
  config.py            # paths + model names, all env-var overridable
  observability.py      # Cloud Trace + Cloud Logging from the ADK event stream
  main.py                # Streamlit UI
  agent.py               # root_agent re-export for `adk web`/`adk run`
  agents/                 # supervisor.py + 6 specialists
  tools/                  # members, id_card, providers, claims, billing, knowledge, escalation
  rag/
    build_index.py
    knowledge/*.md
  data/*.json             # mock members, plans, providers, claims
  prompts/system_prompt.md
  generated/              # runtime PDFs (VSP_GENERATED_DIR overrides; use /tmp on Cloud Run)
tests/                    # pytest, no GCP credentials required
requirements.txt
Dockerfile
```

## Scope

In scope (per the hackathon brief): logged-in members, the top
self-service topics (ID card, benefits/eligibility, find-a-doctor,
claims, OON reimbursement, IP billing), guided structured answers with a
clear next step. Out of scope: account creation/login/password flows,
live production data, general customer service unrelated to
self-service.
