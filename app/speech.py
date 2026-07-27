"""Voice-input transcription for the chat's audio input.

Sends recorded audio straight to Gemini for transcription (multimodal input)
rather than adding a separate speech-to-text dependency or GCP API -- this
repo already talks to Gemini via google-genai, so this reuses that same
credential/model setup. Supports English, Hindi, and Spanish by asking the
model to auto-detect the spoken language and, in the same call, translate to
English -- the English text is what drives the existing chat routing
(app/frames.py's keyword heuristics and the agent's system prompt are
English), while the original-language text is what's echoed back into the
chat as "what you said".
"""

import json
from dataclasses import dataclass

from google import genai
from google.genai import types

from app.config import SPECIALIST_MODEL

_PROMPT = (
    "Transcribe the spoken audio. The speaker may be using English, Hindi, "
    "or Spanish. Respond with ONLY strict JSON and nothing else -- no "
    "markdown code fences, no commentary before or after -- in exactly this "
    'shape: {"language": "<ISO 639-1 code, e.g. en, hi, es>", '
    '"original_text": "<verbatim transcript in the language spoken>", '
    '"english_text": "<natural English translation of what was said>"}. '
    "If the audio is silent, unintelligible, or contains no speech, return "
    '{"language": "", "original_text": "", "english_text": ""}.'
)


@dataclass
class Transcript:
    language: str
    original_text: str
    english_text: str

    @property
    def is_empty(self) -> bool:
        return not self.original_text.strip() and not self.english_text.strip()


_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def _parse_transcript_response(raw: str) -> Transcript:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if "\n" in text:
            first_line, rest = text.split("\n", 1)
            text = rest if first_line.strip().lower() in ("json", "") else text
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return Transcript(language="", original_text="", english_text="")
    if not isinstance(data, dict):
        return Transcript(language="", original_text="", english_text="")
    return Transcript(
        language=str(data.get("language") or ""),
        original_text=str(data.get("original_text") or ""),
        english_text=str(data.get("english_text") or ""),
    )


def transcribe_audio(audio_bytes: bytes, mime_type: str = "audio/wav") -> Transcript:
    client = _get_client()
    response = client.models.generate_content(
        model=SPECIALIST_MODEL,
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                    types.Part.from_text(text=_PROMPT),
                ],
            )
        ],
    )
    return _parse_transcript_response(response.text)
