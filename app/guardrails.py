"""Guardrails: Gemini content-safety thresholds, local PII redaction, and a
prompt-injection backstop.

Deliberately dependency-light and Vertex/Developer-API agnostic:
- SAFETY_SETTINGS uses only the four harm categories supported on both
  surfaces (Vertex AI and the Gemini Developer API) -- Vertex-only categories
  like HARM_CATEGORY_JAILBREAK are left out so this doesn't behave
  differently (or error) depending on which one is configured.
- PII redaction uses Presidio entirely locally (no external API, no token),
  so it also works unchanged on either surface.
"""

import logging
import re

from google.genai import types

logger = logging.getLogger("vsp.guardrails")

SAFETY_SETTINGS = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    ),
]

# Entities redacted from anything headed to Cloud Logging/Trace or (via the
# before_model_callback below) flagged for injection screening. Deliberately
# excludes LOCATION -- zip codes drive find_doctor_agent and come from the
# member's own profile data, not typed text, so there's no PII upside to
# flagging a city/zip a member happens to type.
_PII_ENTITIES = ["PERSON", "PHONE_NUMBER", "EMAIL_ADDRESS", "US_SSN", "CREDIT_CARD"]

_PII_ANALYZER = None
_PII_ANONYMIZER = None


def _get_pii_engines():
    """Lazily build the Presidio engines, pinned to the small spaCy model
    (en_core_web_sm) that's what actually gets downloaded in the Dockerfile --
    Presidio's own default configuration otherwise pulls the 400MB
    en_core_web_lg on first use, which isn't installed there."""
    global _PII_ANALYZER, _PII_ANONYMIZER
    if _PII_ANALYZER is None:
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        nlp_engine = NlpEngineProvider(
            nlp_configuration={
                "nlp_engine_name": "spacy",
                "models": [{"lang_code": "en", "model_name": "en_core_web_sm"}],
            }
        ).create_engine()
        _PII_ANALYZER = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])
        _PII_ANONYMIZER = AnonymizerEngine()
    return _PII_ANALYZER, _PII_ANONYMIZER


def redact_pii(text: str) -> str:
    """Replace names/emails/phone numbers/SSNs/credit-card numbers in `text`
    with placeholders like "<PERSON>". Used before anything free-text goes
    into Cloud Logging (see app/observability.py) -- member questions
    routinely include their own name or contact info, and that shouldn't end
    up sitting in plaintext in Cloud Logging."""
    if not text:
        return text
    analyzer, anonymizer = _get_pii_engines()
    try:
        results = analyzer.analyze(text=text, language="en", entities=_PII_ENTITIES)
        if not results:
            return text
        return anonymizer.anonymize(text=text, analyzer_results=results).text
    except Exception:
        logger.warning("PII redaction failed; returning original text unredacted.", exc_info=True)
        return text


# Deliberately simple substring/regex heuristics rather than a model call --
# this runs on every turn before the real request, so it needs to be cheap
# and dependency-free. It's a backstop, not the only line of defense: the
# supervisor's own system prompt (app/prompts/system_prompt.md) already
# instructs it to stay in its lane and never role-play a different identity.
_INJECTION_PATTERNS = [
    r"ignore (all|any|the) (previous|prior|above) instructions",
    r"disregard (all|any|the) (previous|prior|above)",
    r"you are now (a|an|free|unrestricted|unfiltered|acting as)\b",
    r"forget (all|your|the) (previous|prior)? ?instructions",
    r"reveal (your|the) (system|hidden) prompt",
    r"show me your (system )?instructions",
    r"act as (an? )?(ai|assistant|bot|dan)\b.*(no|without) (restrictions|filters|rules)",
    r"new instructions:",
    r"do anything now",
    r"jailbreak",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def looks_like_prompt_injection(text: str) -> bool:
    return bool(text) and bool(_INJECTION_RE.search(text))


_INJECTION_REFUSAL = (
    "I can't follow instructions embedded in a message like that. I'm here "
    "to help with your VSP vision benefits -- your ID card, coverage, "
    "claims, or finding a doctor. What can I help you with there?"
)


def block_injection_callback(callback_context, llm_request):
    """before_model_callback: short-circuits the Gemini call entirely (never
    sends the request) if the member's latest message trips the
    prompt-injection heuristic. Returning a non-None LlmResponse here is how
    ADK's callback contract skips the actual model call for this turn."""
    contents = getattr(llm_request, "contents", None) or []
    last_user_text = ""
    for content in reversed(contents):
        if getattr(content, "role", None) != "user":
            continue
        parts = getattr(content, "parts", None) or []
        last_user_text = "".join(getattr(p, "text", None) or "" for p in parts)
        break

    if not looks_like_prompt_injection(last_user_text):
        return None

    logger.warning("Blocked a prompt-injection attempt before the model call.")
    from google.adk.models import LlmResponse

    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=_INJECTION_REFUSAL)])
    )
