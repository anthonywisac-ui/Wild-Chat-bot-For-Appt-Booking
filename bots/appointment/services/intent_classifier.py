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

CRITICAL — do not confuse these two:
- "complaint": the patient is unhappy, frustrated, or criticizing the clinic/bot/service
  (e.g. "this is taking forever", "you're not understanding me", "this is wrong",
  "I'm not happy with this", sarcasm, venting). This is BY FAR the more common case.
- "emergency": the patient is describing an ACTUAL medical/health crisis happening to
  them right now (e.g. severe pain, can't breathe, heavy bleeding, allergic reaction,
  fainting, chest pain). Only use "emergency" when a real medical symptom or danger is
  described — frustration with the conversation itself is ALWAYS "complaint", never
  "emergency", no matter how angry the wording is.

Extract any entities mentioned (in THIS message or implied by context) — only include fields with real values:
- patient_name
- concern (their symptom/reason, in their own words)
- department (one of: "skin", "hair", "laser", "injectables", "body", "dental" — infer from treatment if not stated directly)
- treatment (procedure name, in their own words)
- doctor_preference (gender, name, or any preference mentioned)
- date (their phrasing, e.g. "tomorrow", "next Friday")
- time (their phrasing, e.g. "after 6", "morning")
- age (if mentioned)
- gender (the PATIENT's gender, if mentioned — distinct from doctor_preference)
- city (if mentioned)
- allergies (if mentioned, including "none"/"no allergies")
- medical_conditions (e.g. diabetes, blood pressure, any condition mentioned, including "none")
- pregnancy_status (if relevant and mentioned, e.g. "pregnant", "not pregnant", "breastfeeding")
- current_medications (if mentioned, including "none")
- previous_treatments (any prior aesthetic/dental treatments mentioned)
- goal (their underlying motivation, e.g. "Bridal Glow", "Hair Regrowth", "Event Preparation" — infer from context, not just literal words)
- secondary_concern (a second concern mentioned alongside the main one, if any)
- timeline (any deadline/event mentioned, e.g. "2 months", "before Eid", "next week")
- budget_level (only if they hint at budget sensitivity or generosity — "low", "medium", or "high"; omit if unclear)
- lead_quality (your read of how ready/serious this lead is to book — "low", "medium", or "high", based on specificity and urgency of their message)
- buying_intention (a short phrase capturing their readiness, e.g. "actively comparing clinics", "just researching", "ready to book this week")

Then list missing_information needed to complete their request (only relevant ones, from: treatment, department, doctor_preference, date, time, patient_name, age, gender, allergies, medical_conditions, pregnancy_status, current_medications) — base this on what's STILL unknown after combining with what we already know above, not just this message alone. Only ask for medical screening fields when the intent is appointment_booking AND they aren't already known.

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
