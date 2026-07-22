FROM python:3.11-slim

WORKDIR /srv/app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Cloud Run's container filesystem is writable but ephemeral per-instance;
# /tmp is the safest bet across Cloud Run generations.
ENV VSP_GENERATED_DIR=/tmp/vsp_generated
ENV VSP_CHROMA_DIR=/tmp/vsp_chroma_store
ENV GOOGLE_GENAI_USE_VERTEXAI=TRUE

# Must be set before the `streamlit` process starts, not inside the app --
# Streamlit's own CLI bootstrap imports protobuf-based modules before any
# app code runs, which locks in the C++ implementation process-wide and
# breaks chromadb's bundled OTLP exporter otherwise. See app/config.py.
ENV PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python

EXPOSE 8080
CMD ["streamlit", "run", "app/main.py", "--server.port=8080", "--server.address=0.0.0.0"]
