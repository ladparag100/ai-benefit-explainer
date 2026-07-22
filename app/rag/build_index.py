"""Chunk the knowledge markdown, embed it via Vertex AI, and upsert into
ChromaDB.

Run directly with:

    python -m app.rag.build_index

`query_knowledge` (app/tools/knowledge.py) also calls `build_index()`
automatically the first time it sees an empty collection, so this doubles
as a self-healing safety net for local dev / demo purposes. For a
production deploy with multiple Cloud Run instances, prefer running this
once against a shared/persistent chroma_store rather than relying on each
cold-started instance to index itself independently.
"""

import os
from pathlib import Path
from typing import Optional

# Import order matters: app.config sets PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION
# before chromadb is imported anywhere -- see the comment in app/config.py.
from app.config import (
    CHROMA_COLLECTION,
    CHROMA_DIR,
    EMBEDDING_MODEL,
    GOOGLE_CLOUD_LOCATION,
    GOOGLE_CLOUD_PROJECT,
    KNOWLEDGE_DIR,
)

import chromadb

PLAN_NAMES = ["Enhanced Advantage", "Signature", "Choice", "Advantage"]

_genai_client = None


def _get_genai_client():
    """Mirrors how google-adk itself picks a backend: GOOGLE_GENAI_USE_VERTEXAI
    controls Vertex AI vs. the Gemini Developer API (GOOGLE_API_KEY), so the
    RAG embedding client stays consistent with whatever the agents are using
    rather than hardcoding Vertex."""
    global _genai_client
    if _genai_client is None:
        from google import genai

        if os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").upper() in ("TRUE", "1"):
            _genai_client = genai.Client(
                vertexai=True,
                project=GOOGLE_CLOUD_PROJECT,
                location=GOOGLE_CLOUD_LOCATION,
            )
        else:
            _genai_client = genai.Client()  # picks up GOOGLE_API_KEY from env
    return _genai_client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via the current Vertex AI embedding model.

    Isolated in its own function because the exact google-genai response
    shape is the single most likely thing to drift between SDK versions --
    if this raises, check `response` against the current google-genai docs
    rather than guessing at the fix.
    """
    client = _get_genai_client()
    response = client.models.embed_content(model=EMBEDDING_MODEL, contents=texts)
    embeddings = getattr(response, "embeddings", None)
    if not embeddings:
        raise RuntimeError(
            "Unexpected embed_content() response shape from google-genai -- "
            "check the installed google-genai version's embeddings API."
        )
    return [list(e.values) for e in embeddings]


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    _, fm_block, body = parts
    meta = {}
    for line in fm_block.strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, body.strip()


def _split_sections(body: str) -> list[tuple[Optional[str], str]]:
    """Split on level-2 (##) headers. No ## headers -> whole body as one section."""
    lines = body.splitlines()
    sections: list[tuple[Optional[str], list[str]]] = []
    heading: Optional[str] = None
    current: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if current:
                sections.append((heading, current))
            heading = line[3:].strip()
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append((heading, current))
    if not sections:
        return [(None, body)]
    return [(h, "\n".join(l).strip()) for h, l in sections]


def _split_by_words(text: str, target_words: int = 300, max_words: int = 450) -> list[str]:
    """Word-count is a rough stand-in for a real tokenizer -- good enough to
    keep chunks in the ~200-400 token ballpark without adding a tokenizer
    dependency."""
    words = text.split()
    if len(words) <= max_words:
        return [text]
    return [" ".join(words[i : i + target_words]) for i in range(0, len(words), target_words)]


def _detect_plan(text: str, default: str) -> str:
    found = {p for p in PLAN_NAMES if p in text}
    # "Advantage" is a substring of "Enhanced Advantage" -- if both matched,
    # the text only actually names the one, more specific plan.
    found = {p for p in found if not any(p != other and p in other for other in found)}
    if len(found) == 1:
        return next(iter(found))
    return default


def _chunk_markdown(path: Path) -> list[dict]:
    frontmatter, body = _parse_frontmatter(path.read_text())
    source = frontmatter.get("source", path.stem)
    default_plan = frontmatter.get("plan", "all")
    default_topic = frontmatter.get("topic", path.stem)
    default_section = frontmatter.get("section", path.stem)

    chunks = []
    for idx, (heading, section_text) in enumerate(_split_sections(body)):
        if not section_text.strip():
            continue
        section_name = heading or default_section
        for sub_idx, sub_text in enumerate(_split_by_words(section_text)):
            chunks.append(
                {
                    "id": f"{source}-{idx}-{sub_idx}",
                    "text": sub_text,
                    "metadata": {
                        "source": source,
                        "section": section_name,
                        "plan": _detect_plan(sub_text, default_plan),
                        "topic": default_topic,
                    },
                }
            )
    return chunks


def build_index(collection=None) -> int:
    """Chunk + embed + upsert every knowledge markdown file. Returns the
    number of chunks indexed. Safe to re-run (upserts by id)."""
    if collection is None:
        client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        collection = client.get_or_create_collection(CHROMA_COLLECTION)

    chunks = []
    for md_path in sorted(KNOWLEDGE_DIR.glob("*.md")):
        chunks.extend(_chunk_markdown(md_path))

    if not chunks:
        return 0

    ids = [c["id"] for c in chunks]
    documents = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]
    embeddings = embed_texts(documents)

    collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)
    return len(chunks)


if __name__ == "__main__":
    count = build_index()
    print(f"Indexed {count} chunks into {CHROMA_DIR} (collection: {CHROMA_COLLECTION})")
