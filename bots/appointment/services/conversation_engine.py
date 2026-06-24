# bots/appointment/services/conversation_engine.py
#
# Orchestrates a single conversational turn:
#   1. Load memory (everything we know about this patient so far)
#   2. Classify the message into structured understanding (intent + entities)
#   3. Merge new entities into memory (never lose what we already knew)
#   4. Route to the right service based on intent
#   5. Compose a natural reply
#   6. Save memory
#
# This replaces the old fixed-stage state machine. There is no "current step"
# the patient must follow — only a set of facts we're gradually filling in,
# and the engine decides what's still needed after every single message.

from __future__ import annotations

import logging
import re

from db import get_doctors_by_bot, get_procedures_by_bot, get_doctor_by_id, log_bot_event
from whatsapp_handlers import send_text_message_v2, send_document_v2
from utils_pdf import generate_appointment_pdf

from bots.appointment.services import conversation_memory as memory_store
from bots.appointment.services import intent_classifier
from bots.appointment.services import appointment_service
from bots.appointment.services import knowledge_service
from bots.appointment.services import response_composer

logger = logging.getLogger(__name__)

_AFFIRMATIVE_RE = re.compile(r"^(yes|yep|yeah|confirm|sure|ok(ay)?|sounds good|go ahead|book it)\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile(r"^(no|nope|not yet|cancel|wait|hold on|change)\b", re.IGNORECASE)


async def _send(sender, text, bot):
    await send_text_message_v2(sender, text, bot)


async def _reconnect_to_pending_request(memory: dict, bot, db) -> str | None:
    """After answering a side question, naturally steer back to whatever the
    patient was in the middle of — instead of just dropping the topic."""
    if not (memory.get("treatment") or memory.get("department") or memory.get("concern")):
        return None
    if memory.get("date_iso") and memory.get("time_24h"):
        return None  # already fully resolved, nothing to steer back to

    validation = await appointment_service.resolve_and_validate(memory, bot, db)
    if not validation["missing"]:
        return None

    directive = (
        "Briefly transition back to their appointment request with a phrase like "
        f"'Coming back to your appointment...' and ask for: {validation['missing'][0]}."
    )
    return await response_composer.compose(directive, memory, bot, db)


async def _handle_booking_intent(sender, memory: dict, bot, db) -> str:
    validation = await appointment_service.resolve_and_validate(memory, bot, db)

    if validation["blocking_error"]:
        directive = (
            f"The patient's requested date/time doesn't work: {validation['blocking_error']} "
            "Apologize briefly and ask for an alternative."
        )
        memory["pending_question"] = directive
        return await response_composer.compose(directive, memory, bot, db)

    if validation["missing"]:
        next_field = validation["missing"][0]
        directive = f"Ask the patient for their {next_field.replace('_', ' ')}, naturally, using everything we already know."
        memory["pending_question"] = directive
        return await response_composer.compose(directive, memory, bot, db)

    # Everything needed is known — show the summary and ask to confirm.
    memory["awaiting_confirmation"] = True
    summary = appointment_service.booking_summary_text(memory, bot, db)
    lead_in = await response_composer.compose(
        "Let the patient know you have everything you need and you're about to confirm their booking. Keep it to one short sentence.",
        memory, bot, db,
    )
    return f"{lead_in}\n\n📝 *{summary}*\n\nShall I confirm this booking?"


async def _finalize_booking(sender, memory: dict, bot, db) -> str:
    appt = appointment_service.finalize_booking(memory, bot, db, sender)
    doctor = get_doctor_by_id(db, bot.id, appt.doctor_id) if appt.doctor_id else None

    try:
        file_path = generate_appointment_pdf(appt, bot, doctor=doctor)
        await send_document_v2(
            sender, file_path, f"appointment_{appt.id}.pdf", bot,
            caption=f"Appointment #{appt.id} confirmation",
        )
    except Exception as exc:
        logger.warning(f"[conversation_engine] PDF send failed: {exc}")

    memory_store.reset_booking_fields(memory)
    memory["awaiting_confirmation"] = False
    return "✅ You're all booked! I've sent your confirmation as a PDF above. Is there anything else I can help with?"


async def handle_turn(sender: str, text: str, bot, db) -> None:
    memory = memory_store.load_memory(db, bot.id, sender)
    memory = appointment_service.load_patient_profile(memory, bot, db, sender)
    memory_store.append_history(memory, "user", text)

    # A pending yes/no confirmation takes priority over re-classifying the message —
    # "yes" should never get misread as casual chat and dropped.
    if memory.get("awaiting_confirmation"):
        if _AFFIRMATIVE_RE.match(text.strip()):
            reply = await _finalize_booking(sender, memory, bot, db)
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
            return
        if _NEGATIVE_RE.match(text.strip()):
            memory["awaiting_confirmation"] = False
            reply = await response_composer.compose(
                "The patient wants to change something about their pending booking before confirming. "
                "Ask what they'd like to change.",
                memory, bot, db,
            )
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
            return

    doctors = get_doctors_by_bot(db, bot.id)
    procedures = get_procedures_by_bot(db, bot.id)
    understanding = await intent_classifier.classify(text, memory, bot, db, doctors, procedures)
    intent = understanding["intent"]
    memory = memory_store.merge_entities(memory, understanding.get("entities", {}))
    memory["last_intent"] = intent

    reply: str

    if intent == "greeting":
        reply = await response_composer.compose(
            "Greet the patient warmly and ask how you can help them today.", memory, bot, db,
        )

    elif intent == "appointment_booking":
        reply = await _handle_booking_intent(sender, memory, bot, db)

    elif intent == "appointment_view":
        appointments = appointment_service.list_upcoming(bot, db, sender)
        if not appointments:
            reply = await response_composer.compose(
                "Let the patient know they have no upcoming appointments and offer to book one.", memory, bot, db,
            )
        else:
            lines = []
            for a in appointments:
                doc = get_doctor_by_id(db, bot.id, a.doctor_id) if a.doctor_id else None
                doc_line = f" with Dr. {doc.name}" if doc else ""
                lines.append(f"🔖 #{a.id} — {a.service or 'Appointment'}{doc_line}\n📅 {a.appointment_date} ⏰ {a.appointment_time}")
            reply = "📋 *Your Upcoming Appointments:*\n\n" + "\n\n".join(lines)

    elif intent == "appointment_cancel":
        appointments = appointment_service.list_upcoming(bot, db, sender)
        if not appointments:
            reply = await response_composer.compose(
                "The patient wants to cancel but has no upcoming appointments. Let them know gently.", memory, bot, db,
            )
        elif len(appointments) == 1:
            appointment_service.cancel(db, appointments[0])
            reply = f"❌ Your appointment #{appointments[0].id} on {appointments[0].appointment_date} has been cancelled."
        else:
            lines = [f"🔖 #{a.id} — {a.service} on {a.appointment_date} {a.appointment_time}" for a in appointments]
            reply = "Which appointment would you like to cancel? Reply with the number:\n\n" + "\n".join(lines)
            memory["pending_question"] = "awaiting_cancel_id"

    elif intent == "appointment_reschedule":
        appointments = appointment_service.list_upcoming(bot, db, sender)
        entities = understanding.get("entities", {})
        if not appointments:
            reply = await response_composer.compose(
                "The patient wants to reschedule but has no upcoming appointments. Let them know gently.", memory, bot, db,
            )
        elif len(appointments) == 1 and entities.get("date") and entities.get("time"):
            appt = appointments[0]
            doctor = get_doctor_by_id(db, bot.id, appt.doctor_id) if appt.doctor_id else None
            temp_memory = {"date_text": entities["date"], "time_text": entities["time"], "doctor_id": appt.doctor_id}
            error = await appointment_service.normalize_date_time(temp_memory, bot, db)
            if error:
                reply = await response_composer.compose(f"Can't reschedule to that time: {error} Ask for an alternative.", memory, bot, db)
            else:
                appointment_service.reschedule(db, appt, temp_memory["date_iso"], temp_memory["time_24h"])
                reply = f"🔁 Your appointment #{appt.id} has been rescheduled to {temp_memory['date_iso']} at {temp_memory['time_24h']}."
        else:
            lines = [f"🔖 #{a.id} — {a.service} on {a.appointment_date} {a.appointment_time}" for a in appointments]
            reply = "Which appointment would you like to reschedule, and what's the new date/time?\n\n" + "\n".join(lines)
            memory["pending_question"] = "awaiting_reschedule_details"

    elif intent in ("treatment_information", "pricing_question", "doctor_information", "clinic_information"):
        answer = await knowledge_service.answer(text, bot, db)
        follow_up = await _reconnect_to_pending_request(memory, bot, db)
        reply = f"{answer}\n\n{follow_up}" if follow_up else answer

    elif intent == "complaint":
        log_bot_event(bot.id, "PATIENT_COMPLAINT", text[:300], customer_phone=sender)
        reply = await response_composer.compose(
            "The patient has a complaint. Acknowledge it empathetically, apologize for the "
            "inconvenience, and reassure them the clinic team will personally follow up.",
            memory, bot, db,
        )

    elif intent == "emergency":
        log_bot_event(bot.id, "PATIENT_EMERGENCY", text[:300], customer_phone=sender)
        reply = await response_composer.compose(
            "This may be a medical emergency. Advise them to call the clinic directly right away, "
            "or seek emergency care if it's severe. Reassure them the clinic team is being notified immediately.",
            memory, bot, db,
        )

    else:  # casual_conversation
        reply = await response_composer.compose(
            f"Respond naturally and warmly to the patient's message: '{text}'.", memory, bot, db,
        )
        follow_up = await _reconnect_to_pending_request(memory, bot, db)
        if follow_up:
            reply = f"{reply}\n\n{follow_up}"

    memory_store.append_history(memory, "assistant", reply)
    memory_store.save_memory(db, bot.id, sender, memory)
    await _send(sender, reply, bot)
