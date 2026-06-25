# bots/appointment/services/response_composer.py
#
# Turns a plain-English "directive" (what needs to be communicated) into the
# actual WhatsApp reply, in the clinic's voice: warm, professional, premium —
# like an experienced human receptionist, never robotic.
#
# Used for: asking for missing info, greetings, casual conversation,
# complaints/emergencies, and re-anchoring back to a pending appointment
# after answering a side question.
#
# NOT used for anything involving exact numbers (fees, dates, appointment IDs)
# — those are rendered as deterministic text elsewhere so the model can't
# misstate a price or a confirmed time.

from __future__ import annotations

import logging

from bots.appointment.services.conversation_memory import known_facts_summary, history_as_text
from bots.appointment.services.language_policy import LANGUAGE_RULE

logger = logging.getLogger(__name__)

_PERSONALITY = (
    "You are the AI receptionist for {business_name}, a premium Dental & Aesthetic clinic. "
    "Sound professional, warm, and reassuring — like an experienced human receptionist at a "
    "high-end clinic, never like a chatbot. "
    "Never say things like 'invalid input', 'I cannot understand', 'choose an option', or "
    "'according to my database'. Instead say things like \"I'd be happy to help\" or "
    "\"May I ask a few details so I can guide you better?\". "
    "Keep replies SHORT — 1-2 sentences max, WhatsApp style, never an essay. "
    "Ask only ONE question per reply. "
    "Check 'What we already know about this patient' below before asking anything — "
    "NEVER ask for something that's already listed there, and never repeat the exact "
    "same question you can see you already asked. "
    "Never diagnose medical conditions or guarantee treatment outcomes.\n\n"
    + LANGUAGE_RULE
)


async def compose(directive: str, memory: dict, bot, db) -> str:
    """directive: a plain instruction describing what this reply should accomplish,
    e.g. 'Ask what date works for their Botox appointment with Dr. Sara, in the evening
    as they mentioned.' or 'Greet the patient warmly and ask how you can help.'"""
    system_prompt = (
        _PERSONALITY.format(business_name=bot.business_name or bot.name)
        + "\n\nWhat we already know about this patient:\n"
        + known_facts_summary(memory)
        + "\n\nRecent conversation:\n"
        + (history_as_text(memory) or "(no prior messages)")
        + "\n\nYour task right now: "
        + directive
    )

    try:
        from ai_utils import resolve_provider_and_key, call_ai_chat

        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return directive  # last-resort: still say *something* useful

        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": directive}]
        return await call_ai_chat(messages, provider, api_key, bot, db, directive)
    except Exception as exc:
        logger.error(f"[response_composer] compose failed: {exc}")
        return "I'd be happy to help with that — could you tell me a bit more?"
