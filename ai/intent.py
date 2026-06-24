# ai/intent.py
#
# Lightweight LLM-based intent classifier for the appointment bot.
# Reuses the same provider/key resolution and chat-call plumbing as ai_utils.py
# so it works with whichever AI provider the bot/owner has configured
# (Groq, Gemini, OpenAI, Minimax, Anthropic, OpenRouter).

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

INTENTS = ["book", "cancel", "reschedule", "view", "faq", "greeting", "other"]

_SYSTEM_PROMPT = (
    "You are an intent classifier for a WhatsApp appointment booking assistant. "
    "Given the user's message, classify it into exactly one of these intents: "
    "book (wants to schedule a new appointment), "
    "cancel (wants to cancel an existing appointment), "
    "reschedule (wants to change date/time of an existing appointment), "
    "view (wants to see their upcoming appointments / list / calendar), "
    "faq (asking a question about the business, e.g. hours, location, pricing, policies), "
    "greeting (hi/hello/start), "
    "other (anything else / smalltalk / unclear). "
    "Reply with ONLY a JSON object like {\"intent\": \"book\"} and nothing else."
)

# Cheap deterministic shortcuts so we don't always burn an LLM call for obvious cases.
_KEYWORD_MAP = [
    (r"\b(hi|hello|hey|start|menu)\b", "greeting"),
    (r"\b(cancel)\b", "cancel"),
    (r"\b(reschedule|change.*(time|date)|move.*appointment)\b", "reschedule"),
    (r"\b(my appointments?|view|list|upcoming|calendar|show.*booking)\b", "view"),
    (r"\b(book|schedule|appointment|reserve)\b", "book"),
]

# If the message looks like a real question, skip the blunt keyword shortcuts above —
# e.g. "Hi, can you tell me your address?" must NOT short-circuit to "greeting" just
# because it contains "hi". Let the LLM read the whole sentence instead.
_QUESTION_MARKERS = (
    "?", "what", "who ", "when ", "where ", "why ", "how ",
    "can you", "could you", "do you", "does ", "is there", "are there",
    "tell me", "explain", "how much", "how many",
)


def looks_like_question(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _QUESTION_MARKERS)


def keyword_intent(text: str) -> str | None:
    if looks_like_question(text):
        return None
    lowered = text.lower().strip()
    for pattern, intent in _KEYWORD_MAP:
        if re.search(pattern, lowered):
            return intent
    return None


async def detect_intent(text: str, bot, db) -> str:
    """
    Returns one of INTENTS. Tries a fast keyword shortcut first; falls back to
    an LLM classification call when the message doesn't match an obvious pattern.
    """
    shortcut = keyword_intent(text)
    if shortcut:
        return shortcut

    try:
        from ai_utils import resolve_provider_and_key, call_ai_chat

        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return "other"

        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        raw = await call_ai_chat(messages, provider, api_key, bot, db, text)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            intent = data.get("intent", "other")
            if intent in INTENTS:
                return intent
    except Exception as exc:
        logger.warning(f"[intent] classification failed, defaulting to 'other': {exc}")

    return "other"
