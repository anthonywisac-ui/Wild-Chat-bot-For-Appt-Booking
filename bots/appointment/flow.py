# bots/appointment/flow.py
#
# Full-featured WhatsApp appointment booking agent.
# Brings the feature set of the reference Streamlit "ai-appointment-agent"
# (NLU intent detection, RAG knowledge base, calendar/list view, PDF export)
# onto the WhatsApp channel using this platform's multi-tenant infra.
#
# Flow summary:
#   1. Every inbound message (when not mid-booking) is classified via
#      ai/intent.py into: book | cancel | reschedule | view | faq | greeting | other
#   2. book        -> guided service/date/time collection -> confirm -> save +
#                     send a PDF confirmation document
#   3. view        -> lists the customer's upcoming appointments (calendar/list view)
#   4. cancel      -> picks an appointment by ID and marks it Cancelled
#   5. reschedule  -> picks an appointment by ID, collects new date/time
#   6. faq         -> answered via the bot's RAG knowledge base (ai/rag.py);
#                     falls back to the general AI assistant if no KB match
#   7. other       -> general AI assistant reply (get_ai_response)

import json
import logging

from db import (
    get_session_data, save_session_data,
    create_appointment, get_upcoming_appointments, get_appointment_by_id,
    cancel_appointment, reschedule_appointment,
)
from whatsapp_handlers import send_text_message_v2, send_document_v2
from ai.intent import detect_intent
from ai.rag import answer_with_rag
from ai_utils import get_ai_response
from utils_pdf import generate_appointment_pdf

logger = logging.getLogger(__name__)

BOOKING_STAGES = {"select_service", "select_date", "select_time", "confirm"}


def _get_services(bot) -> list:
    try:
        config = json.loads(bot.config_json) if bot.config_json else {}
    except Exception:
        config = {}
    return config.get("services", ["Consultation", "Maintenance", "General Inquiry"])


def _get_session(sender, bot_id, db):
    state = get_session_data(db, bot_id, sender)
    return state if state else {"stage": "idle"}


def _save(sender, bot_id, state, db):
    save_session_data(db, bot_id, sender, state)


def _format_appointment_list(appointments) -> str:
    lines = []
    for a in appointments:
        lines.append(
            f"🔖 *#{a.id}* — {a.service or 'Appointment'}\n"
            f"   📅 {a.appointment_date}  ⏰ {a.appointment_time}\n"
            f"   Status: {a.status}"
        )
    return "\n\n".join(lines)


async def _send_welcome(sender, bot, db):
    msg = (
        f"📅 Hello! Welcome to *{bot.business_name or bot.name}* Booking Assistant.\n\n"
        "I can help you:\n"
        "• 📝 *Book* a new appointment\n"
        "• 📋 *View* your appointments\n"
        "• 🔁 *Reschedule* an appointment\n"
        "• ❌ *Cancel* an appointment\n"
        "• ❓ Ask a question (hours, location, pricing...)\n\n"
        "Just tell me what you'd like to do!"
    )
    await send_text_message_v2(sender, msg, bot)


async def _start_booking(sender, bot, db, session):
    services = _get_services(bot)
    options = "\n".join([f"- {s}" for s in services])
    msg = f"Great, let's book an appointment!\n\nWhat service would you like?\n{options}"
    await send_text_message_v2(sender, msg, bot)
    session["stage"] = "select_service"
    return session


async def _send_appointment_pdf(sender, bot, appointment, intro_text):
    try:
        file_path = generate_appointment_pdf(appointment, bot)
        await send_text_message_v2(sender, intro_text, bot)
        sent = await send_document_v2(
            sender, file_path, f"appointment_{appointment.id}.pdf", bot,
            caption=f"Appointment #{appointment.id} confirmation",
        )
        if not sent:
            logger.warning(f"[appointment] PDF send failed for appointment #{appointment.id}")
    except Exception as exc:
        logger.error(f"[appointment] PDF generation/send failed: {exc}")


async def handle_flow(sender, text, bot, db):
    session = _get_session(sender, bot.id, db)
    stage = session.get("stage", "idle")
    text_clean = text.strip()
    text_lower = text_clean.lower()

    # ── Universal escape hatch out of any sub-flow ─────────────────────────
    if text_lower in {"menu", "main menu", "start over"}:
        session = {"stage": "idle"}
        await _send_welcome(sender, bot, db)
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # BOOKING SUB-FLOW (structured multi-step collection)
    # ══════════════════════════════════════════════════════════════════════
    if stage in BOOKING_STAGES:
        if text_lower == "cancel":
            await send_text_message_v2(sender, "Booking cancelled. Type *menu* to see what else I can help with.", bot)
            session = {"stage": "idle"}
            _save(sender, bot.id, session, db)
            return

        if stage == "select_service":
            session["service"] = text_clean
            await send_text_message_v2(sender, "Please enter your preferred *Date* (e.g. Tomorrow, Monday, or Oct 25th).", bot)
            session["stage"] = "select_date"

        elif stage == "select_date":
            session["date"] = text_clean
            await send_text_message_v2(sender, "What *Time* works best for you? (e.g. 10 AM, 2:30 PM)", bot)
            session["stage"] = "select_time"

        elif stage == "select_time":
            session["time"] = text_clean
            msg = (
                f"📝 *Confirm Booking:*\n"
                f"🔹 Service: {session['service']}\n"
                f"📅 Date: {session['date']}\n"
                f"⏰ Time: {session['time']}\n\n"
                "Type *Confirm* to book, or *Cancel* to abort."
            )
            await send_text_message_v2(sender, msg, bot)
            session["stage"] = "confirm"

        elif stage == "confirm":
            if "confirm" in text_lower:
                appt = create_appointment(
                    db, owner_id=bot.owner_id, bot_id=bot.id, customer_phone=sender,
                    service=session.get("service", ""), appointment_date=session.get("date", ""),
                    appointment_time=session.get("time", ""),
                )
                await _send_appointment_pdf(
                    sender, bot, appt,
                    "✅ Appointment booked! Here's your confirmation:",
                )
                session = {"stage": "idle"}
            else:
                await send_text_message_v2(sender, "No problem — type *menu* to start again.", bot)
                session = {"stage": "idle"}

        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # CANCEL SUB-FLOW (awaiting which appointment ID)
    # ══════════════════════════════════════════════════════════════════════
    if stage == "await_cancel_id":
        try:
            appt_id = int(text_clean.lstrip("#"))
        except ValueError:
            await send_text_message_v2(sender, "Please reply with just the appointment number, e.g. *3*.", bot)
            return
        appt = get_appointment_by_id(db, bot.id, sender, appt_id)
        if not appt:
            await send_text_message_v2(sender, "I couldn't find that appointment. Type *menu* to try again.", bot)
        else:
            cancel_appointment(db, appt)
            await send_text_message_v2(sender, f"❌ Appointment #{appt.id} has been cancelled.", bot)
        session = {"stage": "idle"}
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # RESCHEDULE SUB-FLOW
    # ══════════════════════════════════════════════════════════════════════
    if stage == "await_reschedule_id":
        try:
            appt_id = int(text_clean.lstrip("#"))
        except ValueError:
            await send_text_message_v2(sender, "Please reply with just the appointment number, e.g. *3*.", bot)
            return
        appt = get_appointment_by_id(db, bot.id, sender, appt_id)
        if not appt:
            await send_text_message_v2(sender, "I couldn't find that appointment. Type *menu* to try again.", bot)
            session = {"stage": "idle"}
        else:
            session = {"stage": "await_reschedule_date", "reschedule_id": appt.id}
            await send_text_message_v2(sender, f"Rescheduling #{appt.id}. What's the new *Date*?", bot)
        _save(sender, bot.id, session, db)
        return

    if stage == "await_reschedule_date":
        session["new_date"] = text_clean
        session["stage"] = "await_reschedule_time"
        await send_text_message_v2(sender, "And what's the new *Time*?", bot)
        _save(sender, bot.id, session, db)
        return

    if stage == "await_reschedule_time":
        appt = get_appointment_by_id(db, bot.id, sender, session.get("reschedule_id"))
        if not appt:
            await send_text_message_v2(sender, "Something went wrong finding that appointment. Type *menu* to try again.", bot)
        else:
            reschedule_appointment(db, appt, session.get("new_date", ""), text_clean)
            await _send_appointment_pdf(
                sender, bot, appt,
                f"🔁 Appointment #{appt.id} rescheduled! Here's your updated confirmation:",
            )
        session = {"stage": "idle"}
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # IDLE / GREETING — classify intent and route
    # ══════════════════════════════════════════════════════════════════════
    intent = await detect_intent(text_clean, bot, db)

    if intent == "greeting":
        await _send_welcome(sender, bot, db)
        session = {"stage": "idle"}

    elif intent == "book":
        session = await _start_booking(sender, bot, db, {"stage": "idle"})

    elif intent == "view":
        appointments = get_upcoming_appointments(db, bot.id, sender)
        if not appointments:
            await send_text_message_v2(sender, "You have no upcoming appointments. Type *book* to schedule one!", bot)
        else:
            msg = "📋 *Your Upcoming Appointments:*\n\n" + _format_appointment_list(appointments)
            await send_text_message_v2(sender, msg, bot)
        session = {"stage": "idle"}

    elif intent == "cancel":
        appointments = get_upcoming_appointments(db, bot.id, sender)
        if not appointments:
            await send_text_message_v2(sender, "You have no upcoming appointments to cancel.", bot)
            session = {"stage": "idle"}
        else:
            msg = "Which appointment would you like to cancel? Reply with the number:\n\n" + _format_appointment_list(appointments)
            await send_text_message_v2(sender, msg, bot)
            session = {"stage": "await_cancel_id"}

    elif intent == "reschedule":
        appointments = get_upcoming_appointments(db, bot.id, sender)
        if not appointments:
            await send_text_message_v2(sender, "You have no upcoming appointments to reschedule.", bot)
            session = {"stage": "idle"}
        else:
            msg = "Which appointment would you like to reschedule? Reply with the number:\n\n" + _format_appointment_list(appointments)
            await send_text_message_v2(sender, msg, bot)
            session = {"stage": "await_reschedule_id"}

    elif intent == "faq":
        answer = await answer_with_rag(text_clean, bot, db)
        if not answer:
            answer = await get_ai_response(sender, text_clean, bot, db)
        await send_text_message_v2(sender, answer, bot)
        session = {"stage": "idle"}

    else:  # "other" — general conversational fallback
        answer = await get_ai_response(sender, text_clean, bot, db)
        await send_text_message_v2(sender, answer, bot)
        session = {"stage": "idle"}

    _save(sender, bot.id, session, db)
