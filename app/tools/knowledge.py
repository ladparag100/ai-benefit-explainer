"""RAG query tool over the Chroma-indexed VSP knowledge base.

Imports from app.rag.build_index are deliberately deferred into the
function bodies below -- that module talks to Vertex AI for embeddings, and
we don't want importing this module (e.g. for unit-testing the other tools)
to require network access or GCP credentials.
"""

from typing import Optional

# Import order matters: app.config sets PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION
# before chromadb is imported anywhere -- see the comment in app/config.py.
from app.config import CHROMA_COLLECTION, CHROMA_DIR

import chromadb

_client: Optional["chromadb.ClientAPI"] = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is not None:
        return _collection

    _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    _collection = _client.get_or_create_collection(CHROMA_COLLECTION)

    if _collection.count() == 0:
        from app.rag.build_index import build_index

        build_index(collection=_collection)

    return _collection


def query_knowledge_impl(query: str, plan: Optional[str] = None, k: int = 4) -> dict:
    from app.rag.build_index import embed_texts

    collection = _get_collection()
    query_embedding = embed_texts([query])[0]

    where = {"plan": {"$in": [plan, "all"]}} if plan else None
    results = collection.query(query_embeddings=[query_embedding], n_results=k, where=where)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    hits = [{"text": text, "meta": meta} for text, meta in zip(docs, metas)]
    return {"query": query, "results": hits}


def query_knowledge(query: str, plan: Optional[str] = None, k: int = 4) -> dict:
    """Search the VSP knowledge base for passages relevant to a question.

    Covers the plan comparison table, common features across all plans,
    worked response examples, and escalation/tone guidance. Always call
    this before answering a general benefits/eligibility/coverage question
    -- never answer plan rules from memory, only from member data (via
    get_member_profile) plus what this returns.

    Args:
        query: the member's question, or a short paraphrase of it.
        plan: optional plan name (Signature, Choice, Advantage, Enhanced
            Advantage) to bias results toward that plan's specifics. Pass
            the member's actual plan once you know it.
        k: how many passages to return.
    """
    return query_knowledge_impl(query, plan, k)
