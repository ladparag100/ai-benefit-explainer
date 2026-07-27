from app.speech import Transcript, _parse_transcript_response


def test_parses_clean_json():
    raw = '{"language": "en", "original_text": "hello", "english_text": "hello"}'
    result = _parse_transcript_response(raw)
    assert result == Transcript(language="en", original_text="hello", english_text="hello")


def test_strips_markdown_code_fence():
    raw = '```json\n{"language": "hi", "original_text": "नमस्ते", "english_text": "hello"}\n```'
    result = _parse_transcript_response(raw)
    assert result.language == "hi"
    assert result.english_text == "hello"


def test_spanish_transcript():
    raw = '{"language": "es", "original_text": "hola", "english_text": "hello"}'
    result = _parse_transcript_response(raw)
    assert result.language == "es"
    assert result.original_text == "hola"


def test_malformed_json_returns_empty_transcript():
    result = _parse_transcript_response("not json at all")
    assert result.is_empty


def test_non_dict_json_returns_empty_transcript():
    result = _parse_transcript_response("[1, 2, 3]")
    assert result.is_empty


def test_silent_audio_response_is_empty():
    raw = '{"language": "", "original_text": "", "english_text": ""}'
    result = _parse_transcript_response(raw)
    assert result.is_empty


def test_missing_keys_default_to_empty_strings():
    result = _parse_transcript_response("{}")
    assert result == Transcript(language="", original_text="", english_text="")
