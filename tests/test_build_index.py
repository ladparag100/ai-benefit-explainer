"""Tests for the pure, offline parts of the RAG pipeline: frontmatter
parsing and chunking. Deliberately does NOT test embed_texts() or
build_index() end-to-end -- those need live Vertex AI credentials and
network access, which unit tests shouldn't depend on."""

from app.config import KNOWLEDGE_DIR
from app.rag.build_index import (
    _chunk_markdown,
    _detect_plan,
    _parse_frontmatter,
    _split_by_words,
)

KNOWLEDGE_FILES = [
    "plan_quick_reference.md",
    "common_features.md",
    "response_examples.md",
    "escalation_and_tone.md",
]


def test_frontmatter_parses_expected_keys():
    text = "---\nsource: foo\nsection: bar\nplan: all\ntopic: baz\n---\n\nbody text here"
    meta, body = _parse_frontmatter(text)
    assert meta == {"source": "foo", "section": "bar", "plan": "all", "topic": "baz"}
    assert body == "body text here"


def test_missing_frontmatter_returns_whole_text_as_body():
    meta, body = _parse_frontmatter("just plain text, no frontmatter")
    assert meta == {}
    assert body == "just plain text, no frontmatter"


def test_split_by_words_respects_max():
    long_text = " ".join(f"word{i}" for i in range(1000))
    chunks = _split_by_words(long_text, target_words=300, max_words=450)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.split()) <= 300


def test_split_by_words_short_text_stays_one_chunk():
    short_text = "This is a short sentence."
    assert _split_by_words(short_text) == [short_text]


def test_detect_plan_single_mention():
    assert _detect_plan("This is about the Choice plan specifically.", default="all") == "Choice"


def test_detect_plan_multiple_mentions_falls_back_to_default():
    text = "Compares Signature and Choice side by side."
    assert _detect_plan(text, default="all") == "all"


def test_detect_plan_prefers_enhanced_advantage_over_advantage_substring():
    assert _detect_plan("Only the Enhanced Advantage plan.", default="all") == "Enhanced Advantage"


def test_all_knowledge_files_chunk_successfully():
    for filename in KNOWLEDGE_FILES:
        path = KNOWLEDGE_DIR / filename
        assert path.exists(), f"missing knowledge file: {filename}"
        chunks = _chunk_markdown(path)
        assert len(chunks) > 0, f"no chunks produced for {filename}"
        for chunk in chunks:
            assert chunk["text"].strip()
            assert set(chunk["metadata"]) == {"source", "section", "plan", "topic"}


def test_response_examples_tag_distinct_plans():
    """Each worked example mentions exactly one plan by name -- confirms the
    plan-detection heuristic is actually distinguishing them, not just
    defaulting everything to "all"."""
    chunks = _chunk_markdown(KNOWLEDGE_DIR / "response_examples.md")
    plans_seen = {c["metadata"]["plan"] for c in chunks}
    assert "Signature" in plans_seen
    assert "Choice" in plans_seen
