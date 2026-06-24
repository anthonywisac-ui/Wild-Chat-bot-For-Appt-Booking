# bots/appointment/services/knowledge_service.py
#
# Answers treatment_information / pricing_question / doctor_information /
# clinic_information intents. Always grounded in real data — either the
# admin's uploaded FAQ knowledge base (RAG) or live facts pulled straight
# from the database. Never allowed to invent services, doctors, or prices.

from __future__ import annotations

import logging

from db import get_doctors_by_bot, get_procedures_by_bot
from ai.rag import answer_with_rag
from bots.appointment.departments import DEPARTMENTS

logger = logging.getLogger(__name__)


def _build_clinic_facts(bot, db) -> str:
    lines = [f"Departments offered: {', '.join(d['label'] for d in DEPARTMENTS.values())}."]

    doctors = get_doctors_by_bot(db, bot.id)
    if doctors:
        for d in doctors:
            bio = f" {d.bio}" if d.bio else ""
            gender = f", {d.gender}" if d.gender else ""
            lines.append(f"Dr. {d.name}{gender} — {d.department.title()} department — consultation fee ${d.consultation_fee:.0f}.{bio}")
    else:
        lines.append("No doctors have been added to the roster yet.")

    procedures = get_procedures_by_bot(db, bot.id)
    for p in procedures:
        lines.append(
            f"Procedure: {p.name} ({p.department.title()}) — ${p.fee_per_session:.0f}/session "
            f"× {p.sessions_required} session(s)."
        )

    return "\n".join(lines)


async def answer(question: str, bot, db) -> str:
    """Tries the admin's FAQ knowledge base first, then falls back to a
    DB-grounded answer. Always returns *something* safe to say — never None."""
    rag_answer = await answer_with_rag(question, bot, db)
    if rag_answer:
        return rag_answer

    facts = _build_clinic_facts(bot, db)
    system_prompt = (
        f"You are a clinic assistant for {bot.business_name or bot.name}. "
        "Answer the patient's question using ONLY the real facts listed below. "
        "If what they're asking isn't covered by these facts, say so plainly and offer to "
        "help them book an appointment or connect with the clinic directly. "
        "NEVER invent services, products, departments, doctors, or prices that aren't listed here. "
        "Sound warm and professional, like an experienced clinic receptionist — not robotic.\n\n"
        f"Known facts:\n{facts}"
    )

    try:
        from ai_utils import resolve_provider_and_key, call_ai_chat

        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return "I'll have our clinic team confirm this for you."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ]
        return await call_ai_chat(messages, provider, api_key, bot, db, question)
    except Exception as exc:
        logger.error(f"[knowledge_service] grounded answer failed: {exc}")
        return "I'll have our clinic team confirm this for you."
