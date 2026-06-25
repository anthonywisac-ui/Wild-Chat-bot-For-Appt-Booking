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
#
# Disambiguation (which appointment to cancel/reschedule, confirm/change a
# booking) always uses real WhatsApp buttons/lists, never "reply with the
# number" — button taps are handled deterministically, bypassing the LLM.

from __future__ import annotations

import logging
import re

from db import get_doctors_by_bot, get_procedures_by_bot, get_doctor_by_id, log_bot_event
from whatsapp_handlers import (
    send_text_message_v2, send_document_v2,
    send_interactive_list, send_interactive_buttons,
)
from utils_pdf import generate_appointment_pdf

from bots.appointment.services import conversation_memory as memory_store
from bots.appointment.services import intent_classifier
from bots.appointment.services import appointment_service
from bots.appointment.services import knowledge_service
from bots.appointment.services import response_composer

logger = logging.getLogger(__name__)

_AFFIRMATIVE_RE = re.compile(r"^(yes|yep|yeah|confirm|sure|ok(ay)?|sounds good|go ahead|book it)\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile(r"^(no|nope|not yet|cancel|wait|hold on|change)\b", re.IGNORECASE)
_CANCEL_BTN_RE = re.compile(r"^CANCEL_(\d+)$")
_RESCHED_BTN_RE = re.compile(r"^RESCHED_(\d+)$")
_PROC_BTN_RE = re.compile(r"^PROC_(\d+)$")
_DOC_BTN_RE = re.compile(r"^DOC_(\d+)$")
_UPSELL_ADD_RE = re.compile(r"^UPSELL_ADD_(\d+)$")
UPSELL_SKIP_ID = "UPSELL_SKIP"

BOOKING_CONFIRM_ID = "BOOKING_CONFIRM"
BOOKING_CHANGE_ID = "BOOKING_CHANGE"
QUICK_CONSULT_ID = "QUICK_CONSULT"
QUICK_ENQUIRY_ID = "QUICK_ENQUIRY"
QUICK_BOOK_ID = "QUICK_BOOK"


async def _send(sender, text, bot):
    await send_text_message_v2(sender, text, bot)


def _appointment_label(a, db, bot) -> str:
    doc = get_doctor_by_id(db, bot.id, a.doctor_id) if a.doctor_id else None
    doc_part = f" w/ Dr. {doc.name}" if doc else ""
    return f"{a.service or 'Appointment'}{doc_part}"


async def _send_appointment_picker(sender, bot, db, appointments, action: str) -> None:
    """action: 'cancel' or 'reschedule' — sends a real WhatsApp list, never numbered text."""
    prefix = "CANCEL_" if action == "cancel" else "RESCHED_"
    rows = [{
        "id": f"{prefix}{a.id}",
        "title": f"#{a.id} {_appointment_label(a, db, bot)}"[:24],
        "description": f"{a.appointment_date} at {a.appointment_time}",
    } for a in appointments[:10]]

    await send_interactive_list(
        sender, "Your Appointments",
        f"Which appointment would you like to {action}?",
        "Select Appointment", [{"title": "Appointments", "rows": rows}], bot,
    )


async def _handle_booking_intent(sender, memory: dict, bot, db) -> str | None:
    validation = await appointment_service.resolve_and_validate(memory, bot, db)

    if validation["procedure_options"]:
        rows = []
        for p in validation["procedure_options"][:10]:
            tier = f" • {p.package_tier}" if p.package_tier else ""
            sessions = f" x{p.sessions_required}" if p.sessions_required > 1 else ""
            rows.append({
                "id": f"PROC_{p.id}", "title": (f"{p.name} ({p.package_tier})" if p.package_tier else p.name)[:24],
                "description": f"${p.fee_per_session:.0f}/session{sessions}{tier}",
            })
        await send_interactive_list(
            sender, "Recommended Treatments", "Which treatment are you interested in?",
            "View Treatments", [{"title": "Treatments", "rows": rows}], bot,
        )
        memory["pending_question"] = "awaiting_procedure_choice"
        return None

    if validation["doctor_options"]:
        rows = [{
            "id": f"DOC_{d.id}", "title": f"Dr. {d.name}"[:24],
            "description": f"${d.consultation_fee:.0f} • {(d.bio or 'Specialist')[:50]}",
        } for d in validation["doctor_options"][:10]]
        await send_interactive_list(
            sender, "Choose a Doctor", "Which doctor would you prefer?",
            "View Doctors", [{"title": "Doctors", "rows": rows}], bot,
        )
        memory["pending_question"] = "awaiting_doctor_choice"
        return None

    # ── Natural, one-time upsell offer once the treatment is locked in ─────
    if memory.get("procedure_id") and not memory.get("upsell_offered"):
        memory["upsell_offered"] = True
        addons = appointment_service.get_upsell_candidates(memory, bot, db)
        if addons:
            buttons = [{"id": f"UPSELL_ADD_{p.id}", "title": f"+ {p.name[:18]}"} for p in addons]
            buttons.append({"id": "UPSELL_SKIP", "title": "No thanks"})
            lines = "\n".join(f"• {p.name} — ${p.fee_per_session * p.sessions_required:.0f}" for p in addons)
            await send_interactive_buttons(
                sender, f"💡 Many clients combine this with:\n{lines}\n\nWould you like to add one?",
                buttons, bot,
            )
            memory["pending_question"] = "awaiting_upsell_choice"
            return None

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

    # Everything needed is known — show the summary and ask to confirm via real buttons.
    memory["awaiting_confirmation"] = True
    summary = appointment_service.booking_summary_text(memory, bot, db)
    lead_in = await response_composer.compose(
        "Let the patient know you have everything you need and you're about to confirm their booking. Keep it to one short sentence.",
        memory, bot, db,
    )
    await send_interactive_buttons(
        sender, f"{lead_in}\n\n📝 *{summary}*",
        [{"id": BOOKING_CONFIRM_ID, "title": "✅ Confirm"}, {"id": BOOKING_CHANGE_ID, "title": "✏️ Change something"}],
        bot,
    )
    return None  # already sent directly


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
    text_stripped_early = text.strip()
    lowered_early = text_stripped_early.lower()

    # ── Testing/admin shortcuts — checked before anything else, never AI-classified ──
    if lowered_early == "-reset":
        from db import reset_customer
        reset_customer(db, bot.id, sender)
        await send_interactive_buttons(
            sender,
            "🔄 All set — starting fresh as a new customer!\n\n"
            f"✨ Welcome to *{bot.business_name or bot.name}*. How can we help you today?",
            [
                {"id": QUICK_CONSULT_ID, "title": "Consult with AI ✨"},
                {"id": QUICK_ENQUIRY_ID, "title": "Treatment Enquiry 💬"},
                {"id": QUICK_BOOK_ID, "title": "Book Appointment 📅"},
            ],
            bot,
        )
        return

    if lowered_early in ("-aesthetic", "-ashtetic"):
        memory = memory_store.load_memory(db, bot.id, sender)
        memory["locked_department"] = "aesthetic"
        reply = "Got it — we'll keep this chat focused on Aesthetic & Cosmetic treatments only. How can I help?"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if lowered_early == "-dental":
        memory = memory_store.load_memory(db, bot.id, sender)
        memory["locked_department"] = "dental"
        reply = "Got it — we'll keep this chat focused on Dental treatments only. How can I help?"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if lowered_early == "-reports":
        from datetime import datetime, timedelta
        from db import get_report_stats
        now = datetime.utcnow()
        daily = get_report_stats(db, bot.id, now - timedelta(days=1))
        weekly = get_report_stats(db, bot.id, now - timedelta(days=7))
        monthly = get_report_stats(db, bot.id, now - timedelta(days=30))

        def _line(label, stats):
            return f"*{label}:* {stats['appointments']} appointments, ${stats['revenue']:.0f} revenue, {stats['leads']} new leads, {stats['cancelled']} cancelled"

        reply = "📊 *Clinic Reports*\n\n" + "\n\n".join([
            _line("Today", daily), _line("This Week", weekly), _line("This Month", monthly),
        ])
        await _send(sender, reply, bot)
        return

    memory = memory_store.load_memory(db, bot.id, sender)
    memory = appointment_service.load_patient_profile(memory, bot, db, sender)
    memory_store.append_history(memory, "user", text)
    text_stripped = text.strip()

    # ── Welcome-screen quick actions — guidance only, never a forced menu ──
    if text_stripped == QUICK_CONSULT_ID:
        reply = "I'd love to understand your concern and suggest the best options. What's bothering you, or what would you like to improve?"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if text_stripped == QUICK_ENQUIRY_ID:
        reply = "Sure! Which treatment or concern would you like to know more about (e.g. pricing, sessions, what's involved)?"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if text_stripped == QUICK_BOOK_ID:
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    # ── Button taps are handled deterministically, never re-classified ─────
    cancel_match = _CANCEL_BTN_RE.match(text_stripped)
    resched_match = _RESCHED_BTN_RE.match(text_stripped)

    if cancel_match:
        appt = appointment_service.find_appointment(bot, db, sender, int(cancel_match.group(1)))
        if not appt:
            reply = "I couldn't find that appointment — it may have already been cancelled. Type *menu* to see options."
        else:
            appointment_service.cancel(db, appt)
            reply = f"❌ Your appointment #{appt.id} on {appt.appointment_date} has been cancelled."
        memory["pending_question"] = None
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if resched_match:
        appt = appointment_service.find_appointment(bot, db, sender, int(resched_match.group(1)))
        if not appt:
            reply = "I couldn't find that appointment. Type *menu* to see options."
            memory["pending_question"] = None
        else:
            memory["appointment_id"] = appt.id
            memory["pending_question"] = "awaiting_reschedule_datetime"
            reply = f"Sure — what new date and time would you like for appointment #{appt.id}?"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    # ── Plain-text replies to a cancel/reschedule list ("#1", "1", "appointment 2") ─
    if memory.get("pending_question") in ("awaiting_cancel_choice", "awaiting_reschedule_choice"):
        num_match = re.search(r"#?\s*(\d+)", text_stripped)
        candidate_ids = memory.get("_candidate_ids") or []
        if num_match and int(num_match.group(1)) in candidate_ids:
            chosen_id = int(num_match.group(1))
            action = "cancel" if memory["pending_question"] == "awaiting_cancel_choice" else "reschedule"
            memory["pending_question"] = None
            memory["_candidate_ids"] = None
            if action == "cancel":
                appt = appointment_service.find_appointment(bot, db, sender, chosen_id)
                if not appt:
                    reply = "I couldn't find that appointment — it may have already been cancelled."
                else:
                    appointment_service.cancel(db, appt)
                    reply = f"❌ Your appointment #{appt.id} on {appt.appointment_date} has been cancelled."
            else:
                appt = appointment_service.find_appointment(bot, db, sender, chosen_id)
                if not appt:
                    reply = "I couldn't find that appointment."
                else:
                    memory["appointment_id"] = appt.id
                    memory["pending_question"] = "awaiting_reschedule_datetime"
                    reply = f"Sure — what new date and time would you like for appointment #{appt.id}?"
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
            return
        # Didn't recognize a valid number — gently re-show the same picker instead of
        # silently falling through to full re-classification (avoids confusing loops).
        if num_match:
            reply = "I couldn't match that to one of the appointments above — could you tap one of the options, or just send its number?"
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
            return

    proc_match = _PROC_BTN_RE.match(text_stripped)
    doc_match = _DOC_BTN_RE.match(text_stripped)

    if proc_match and memory.get("pending_question") == "awaiting_procedure_choice":
        from db import get_procedure_by_id
        proc = get_procedure_by_id(db, bot.id, int(proc_match.group(1)))
        if proc:
            memory["procedure_id"] = proc.id
            memory["treatment"] = proc.name
            memory["department"] = proc.department
            memory["fee_estimate"] = proc.fee_per_session * proc.sessions_required
        memory["pending_question"] = None
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    if doc_match and memory.get("pending_question") == "awaiting_doctor_choice":
        doctor = get_doctor_by_id(db, bot.id, int(doc_match.group(1)))
        if doctor:
            memory["doctor_id"] = doctor.id
            if not memory.get("fee_estimate"):
                memory["fee_estimate"] = doctor.consultation_fee
        memory["pending_question"] = None
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    upsell_add_match = _UPSELL_ADD_RE.match(text_stripped)
    if memory.get("pending_question") == "awaiting_upsell_choice" and (upsell_add_match or text_stripped == UPSELL_SKIP_ID):
        if upsell_add_match:
            from db import get_procedure_by_id
            addon = get_procedure_by_id(db, bot.id, int(upsell_add_match.group(1)))
            if addon:
                addon_fee = addon.fee_per_session * addon.sessions_required
                memory["fee_estimate"] = (memory.get("fee_estimate") or 0.0) + addon_fee
                memory["treatment"] = f"{memory.get('treatment') or 'Treatment'} + {addon.name}"
        memory["pending_question"] = None
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    # ── Mid-reschedule: this message should contain the new date/time ──────
    if memory.get("pending_question") == "awaiting_reschedule_datetime" and memory.get("appointment_id"):
        appt = appointment_service.find_appointment(bot, db, sender, memory["appointment_id"])
        if not appt:
            reply = "Something went wrong finding that appointment. Type *menu* to start again."
            memory["pending_question"] = None
            memory["appointment_id"] = None
        else:
            doctor = get_doctor_by_id(db, bot.id, appt.doctor_id) if appt.doctor_id else None
            temp_memory = {"date_text": text_stripped, "time_text": text_stripped, "doctor_id": appt.doctor_id}
            # Try to split "date and time" naturally — let the AI-assisted parser do the heavy lifting
            # by attempting the full string against both date and time parsers.
            error = await appointment_service.normalize_date_time(temp_memory, bot, db)
            if error or not temp_memory.get("date_iso"):
                reply = await response_composer.compose(
                    f"Couldn't quite parse a date and time from that. {error or ''} Ask them to provide both clearly, e.g. 'next Monday at 3pm'.",
                    memory, bot, db,
                )
            else:
                appointment_service.reschedule(db, appt, temp_memory["date_iso"], temp_memory["time_24h"])
                reply = f"🔁 Your appointment #{appt.id} has been rescheduled to {temp_memory['date_iso']} at {temp_memory['time_24h']}."
                memory["pending_question"] = None
                memory["appointment_id"] = None
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    # ── A pending booking confirmation takes priority over re-classifying ──
    if memory.get("awaiting_confirmation"):
        if text_stripped == BOOKING_CONFIRM_ID or _AFFIRMATIVE_RE.match(text_stripped):
            reply = await _finalize_booking(sender, memory, bot, db)
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
            return
        if text_stripped == BOOKING_CHANGE_ID or _NEGATIVE_RE.match(text_stripped):
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
    appointment_service.save_lead_snapshot(memory, bot, db, sender)

    reply: str | None = None

    if intent == "greeting":
        lead_in = await response_composer.compose(
            "Greet the patient warmly as a premium aesthetic/dental clinic receptionist. Keep it to one short, welcoming sentence — the next message will show their options.",
            memory, bot, db,
        )
        await send_interactive_buttons(
            sender, lead_in,
            [
                {"id": QUICK_CONSULT_ID, "title": "Consult with AI ✨"},
                {"id": QUICK_ENQUIRY_ID, "title": "Treatment Enquiry 💬"},
                {"id": QUICK_BOOK_ID, "title": "Book Appointment 📅"},
            ],
            bot,
        )
        reply = None

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
                lines.append(f"🔖 #{a.id} — {_appointment_label(a, db, bot)}\n📅 {a.appointment_date} ⏰ {a.appointment_time}")
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
            await _send_appointment_picker(sender, bot, db, appointments, "cancel")
            memory["pending_question"] = "awaiting_cancel_choice"
            memory["_candidate_ids"] = [a.id for a in appointments]
            reply = None

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
        elif len(appointments) == 1:
            memory["appointment_id"] = appointments[0].id
            memory["pending_question"] = "awaiting_reschedule_datetime"
            reply = f"What new date and time would you like for appointment #{appointments[0].id}?"
        else:
            await _send_appointment_picker(sender, bot, db, appointments, "reschedule")
            memory["pending_question"] = "awaiting_reschedule_choice"
            memory["_candidate_ids"] = [a.id for a in appointments]
            reply = None

    elif intent in ("treatment_information", "pricing_question", "doctor_information", "clinic_information"):
        reply = await knowledge_service.answer(text, bot, db)

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
            f"Respond naturally and warmly to the patient's message: '{text}'. "
            "If there's a pending question we just asked them (see known facts), you may gently "
            "circle back to it — but only if it fits naturally, don't force it.",
            memory, bot, db,
        )

    memory_store.append_history(memory, "assistant", reply or "")
    memory_store.save_memory(db, bot.id, sender, memory)
    if reply:
        await _send(sender, reply, bot)
