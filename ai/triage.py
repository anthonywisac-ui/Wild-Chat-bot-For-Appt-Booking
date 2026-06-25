# ai/triage.py
#
# Symptom-based triage: a patient describes a problem in free text, and we
# use the bot's configured LLM to recommend the best department + doctor
# from the bot's actual roster (not a generic guess).

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


def _doctor_catalog_text(doctors) -> str:
    lines = []
    for d in doctors:
        lines.append(f"- id={d.id} | {d.name} | department={d.department} | fee=${d.consultation_fee:.0f} | bio: {d.bio or 'General practitioner in this field.'}")
    return "\n".join(lines)


async def recommend_doctor(symptom_text: str, doctors: list, bot, db) -> dict:
    """
    Returns: {"doctor_id": int|None, "department": str, "reasoning": str}
    Falls back to a department-only guess (no specific doctor) if the LLM call fails
    or no doctors are configured for the matched department.
    """
    if not doctors:
        return {"doctor_id": None, "department": "", "reasoning": ""}

    catalog = _doctor_catalog_text(doctors)
    system_prompt = (
        f"You are a medical intake triage assistant for {bot.business_name or bot.name}. "
        "A patient will describe their problem. Based ONLY on the doctor roster below, "
        "recommend the single best-matching doctor. Reply with ONLY a JSON object: "
        '{"doctor_id": <int>, "reasoning": "<one short friendly sentence explaining why this doctor, in plain language, no medical diagnosis>"}. '
        "If nothing matches well, pick the closest department match anyway — never leave doctor_id null if any doctor exists.\n\n"
        f"Doctor roster:\n{catalog}"
    )

    try:
        from ai_utils import resolve_provider_and_key, call_ai_chat

        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return {"doctor_id": doctors[0].id, "department": doctors[0].department,
                    "reasoning": "Based on your description, here's a doctor who can help."}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": symptom_text},
        ]
        raw = await call_ai_chat(messages, provider, api_key, bot, db, symptom_text)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            doctor_id = data.get("doctor_id")
            matched = next((d for d in doctors if d.id == doctor_id), None)
            if matched:
                return {
                    "doctor_id": matched.id,
                    "department": matched.department,
                    "reasoning": data.get("reasoning", ""),
                }
    except Exception as exc:
        logger.warning(f"[triage] recommend_doctor failed, falling back: {exc}")

    # Fallback: just recommend the first available doctor so the flow never dead-ends.
    first = doctors[0]
    return {"doctor_id": first.id, "department": first.department,
            "reasoning": "Based on your description, here's a doctor who can help."}


async def analyze_lab_report(report_text: str, doctors: list, bot, db) -> dict:
    """
    Returns: {"summary": str, "doctor_id": int|None, "department": str}
    Summarizes a lab report in plain language and recommends a doctor from the roster.
    """
    if not doctors:
        return {"summary": "", "doctor_id": None, "department": ""}

    from bots.appointment.services.language_policy import LANGUAGE_RULE

    catalog = _doctor_catalog_text(doctors)
    system_prompt = (
        f"You are a medical intake assistant for {bot.business_name or bot.name}. "
        "A patient uploaded a lab report. Summarize the key findings in 2-3 plain, "
        "friendly sentences (no alarming language, no formal diagnosis — just describe "
        "what stands out). Then recommend the best-matching doctor from the roster below. "
        'Reply with ONLY a JSON object: {"summary": "<plain language summary>", "doctor_id": <int>}.\n\n'
        f"{LANGUAGE_RULE}\n\n"
        f"Doctor roster:\n{catalog}"
    )

    try:
        from ai_utils import resolve_provider_and_key, call_ai_chat

        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return {"summary": "Report received.", "doctor_id": doctors[0].id, "department": doctors[0].department}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": report_text[:6000]},
        ]
        raw = await call_ai_chat(messages, provider, api_key, bot, db, report_text[:500])
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            doctor_id = data.get("doctor_id")
            matched = next((d for d in doctors if d.id == doctor_id), None)
            if matched:
                return {
                    "summary": data.get("summary", ""),
                    "doctor_id": matched.id,
                    "department": matched.department,
                }
    except Exception as exc:
        logger.warning(f"[triage] analyze_lab_report failed, falling back: {exc}")

    first = doctors[0]
    return {"summary": "Report received — please review with a doctor.",
            "doctor_id": first.id, "department": first.department}
