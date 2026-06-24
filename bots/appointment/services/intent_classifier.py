# bots/appointment/services/intent_classifier.py
#
# Single LLM call that converts a raw patient message into structured
# understanding — replacing keyword/regex matching entirely. The model reads
# the message PLUS what we already know about this patient (conversation
# memory) and returns intent, extracted entities, what's still missing, and
# a suggested next action.
#
# The backend (conversation_engine + appointment_service) treats this as a
# strong hint, not gospel — real availability/business rules are always
# re-verified deterministically. But understanding the message itself is
# 100% the model's job; there is no keyword matching here.

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

INTENT_TYPES = [
    "greeting",
    "appointment_booking",
    "appointment_view",
    "appointment_cancel",
    "appointment_reschedule",
    "treatment_information",
    "pricing_question",
    "doctor_information",
    "clinic_information",
    "complaint",
    "emergency",
    "casual_conversation",
]

_SYSTEM_TEMPLATE = """You are the understanding layer for an AI receptionist at {business_name}, a Dental & Aesthetic clinic.

Your ONLY job is to read the patient's latest WhatsApp message and convert it into structured understanding. You do not write replies — another module handles that.

What we already know about this patient so far:
{known_facts}

Recent conversation:
{history}

The clinic actually offers:
{clinic_catalog}

Classify the LATEST patient message into exactly one intent from this list:
{intent_types}

Extract any entities mentioned (in THIS message or implied by context) — only include fields with real values:
- patient_name
- concern (their symptom/reason, in their own words)
- department ("dental" or "aesthetic" — infer from treatment if not stated directly)
- treatment (procedure name, in their own words)
- doctor_preference (gender, name, or any preference mentioned)
- date (their phrasing, e.g. "tomorrow", "next Friday")
- time (their phrasing, e.g. "after 6", "morning")

Then list missing_information needed to complete their request (only relevant ones, from: treatment, department, doctor_preference, date, time, patient_name) — base this on what's STILL unknown after combining with what we already know above, not just this message alone.

Respond with ONLY this JSON shape, nothing else:
{{
  "intent": "<one of the intent types>",
  "confidence": <0.0-1.0>,
  "entities": {{...only fields with real values...}},
  "missing_information": [...],
  "next_action": "<short description of what should happen next, e.g. 'ask_missing_information', 'confirm_booking', 'answer_question', 'escalate_to_human'>"
}}"""


def _build_catalog_text(doctors, procedures) -> str:
    lines = []
    if doctors:
        for d in doctors:
            gender = f", {d.gender}" if d.gender else ""
            lines.append(f"- Dr. {d.name} ({d.department}{gender}) — consultation ${d.consultation_fee:.0f}")
    if procedures:
        for p in procedures:
            lines.append(f"- {p.name} ({p.department}) — ${p.fee_per_session:.0f}/session x{p.sessions_required}")
    return "\n".join(lines) if lines else "No doctors/procedures configured yet."


async def classify(message: str, memory: dict, bot, db, doctors=None, procedures=None) -> dict:
    """Returns the structured understanding dict described in _SYSTEM_TEMPLATE."""
    from ai_utils import resolve_provider_and_key, call_ai_chat
    from bots.appointment.services.conversation_memory import known_facts_summary, history_as_text

    catalog = _build_catalog_text(doctors or [], procedures or [])
    system_prompt = _SYSTEM_TEMPLATE.format(
        business_name=bot.business_name or bot.name,
        known_facts=known_facts_summary(memory),
        history=history_as_text(memory) or "(no prior messages)",
        clinic_catalog=catalog,
        intent_types=", ".join(INTENT_TYPES),
    )

    fallback = {
        "intent": "casual_conversation",
        "confidence": 0.3,
        "entities": {},
        "missing_information": [],
        "next_action": "answer_question",
    }

    try:
        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return fallback

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]
        raw = await call_ai_chat(messages, provider, api_key, bot, db, message)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return fallback

        data = json.loads(match.group(0))
        if data.get("intent") not in INTENT_TYPES:
            data["intent"] = "casual_conversation"
        data.setdefault("confidence", 0.5)
        data.setdefault("entities", {})
        data.setdefault("missing_information", [])
        data.setdefault("next_action", "answer_question")
        return data
    except Exception as exc:
        logger.warning(f"[intent_classifier] classify failed, using fallback: {exc}")
        return fallback
