# bots/appointment/flow.py
#
# WhatsApp clinic appointment agent — Dental + Aesthetic departments.
#
# Capabilities:
#   - Native WhatsApp List/Button messages for department + doctor selection
#     (auto-degrades to numbered text for wwebjs/self-hosted bots)
#   - Works as a single-specialty clinic demo (only Dental doctors configured)
#     OR a multi-department clinic demo (Dental + Aesthetic both configured) —
#     department selection is skipped automatically if only one department
#     has doctors.
#   - Symptom-based triage: patient describes their problem in free text and
#     the AI recommends the best-matching doctor from the actual roster.
#   - Lab report upload (PDF, Meta provider only): AI reads the report and
#     recommends a doctor.
#   - Booking shows the doctor's name + consultation fee, and the PDF
#     confirmation includes department/doctor/fee.
#   - Cancel / Reschedule / View upcoming appointments / FAQ (RAG) / general
#     AI fallback — same as before, now doctor/fee-aware.

import logging

from db import (
    get_session_data, save_session_data,
    create_appointment, get_upcoming_appointments, get_appointment_by_id,
    cancel_appointment, reschedule_appointment,
    get_doctors_by_bot, get_doctors_by_department, get_doctor_by_id,
    get_enabled_departments_for_bot, create_lab_report,
)
from whatsapp_handlers import (
    send_text_message_v2, send_document_v2,
    send_interactive_list, send_interactive_buttons,
)
from ai.intent import detect_intent
from ai.rag import answer_with_rag
from ai.triage import recommend_doctor, analyze_lab_report
from ai_utils import get_ai_response
from utils_pdf import generate_appointment_pdf
from bots.appointment.departments import DEPARTMENTS, get_department

logger = logging.getLogger(__name__)

BOOKING_STAGES = {"select_date", "select_time", "confirm"}
SYMPTOM_TRIAGE_ID = "SYMPTOM_TRIAGE"


# ──────────────────────────────────────────────────────────────────────────
# Session helpers
# ──────────────────────────────────────────────────────────────────────────

def _get_session(sender, bot_id, db):
    state = get_session_data(db, bot_id, sender)
    return state if state else {"stage": "idle"}


def _save(sender, bot_id, state, db):
    save_session_data(db, bot_id, sender, state)


def _format_appointment_list(appointments, db, bot_id) -> str:
    lines = []
    for a in appointments:
        doctor_line = ""
        if a.doctor_id:
            doc = get_doctor_by_id(db, bot_id, a.doctor_id)
            if doc:
                doctor_line = f"\n   👨‍⚕️ Dr. {doc.name} ({(a.department or doc.department).title()})"
        fee_line = f"\n   💰 Fee: ${a.consultation_fee:.0f}" if a.consultation_fee else ""
        lines.append(
            f"🔖 *#{a.id}* — {a.service or 'Appointment'}{doctor_line}\n"
            f"   📅 {a.appointment_date}  ⏰ {a.appointment_time}{fee_line}\n"
            f"   Status: {a.status}"
        )
    return "\n\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────
# WhatsApp UI builders
# ──────────────────────────────────────────────────────────────────────────

async def _send_welcome(sender, bot, db):
    msg = (
        f"📅 Hello! Welcome to *{bot.business_name or bot.name}*.\n\n"
        "I can help you:\n"
        "• 🩺 *Book* an appointment\n"
        "• 📋 *View* your appointments\n"
        "• 🔁 *Reschedule* an appointment\n"
        "• ❌ *Cancel* an appointment\n"
        "• ❓ Ask a question (hours, location, pricing...)\n"
        "• 📄 Send a lab report (PDF) for a doctor recommendation\n\n"
        "Just tell me what you'd like to do!"
    )
    await send_text_message_v2(sender, msg, bot)


async def _send_department_list(sender, bot, db):
    rows = []
    for slug, info in DEPARTMENTS.items():
        rows.append({"id": f"DEPT_{slug.upper()}", "title": f"{info['emoji']} {info['label']}",
                     "description": info["description"][:72]})
    rows.append({"id": SYMPTOM_TRIAGE_ID, "title": "🤔 Not sure / Describe my problem",
                 "description": "Tell me what's wrong and I'll recommend a doctor"})

    await send_interactive_list(
        sender, "Choose a Department", "Which department would you like to book with?",
        "View Departments", [{"title": "Departments", "rows": rows}], bot,
    )


async def _send_doctor_list(sender, bot, db, department: str):
    doctors = get_doctors_by_department(db, bot.id, department)
    if not doctors:
        await send_text_message_v2(
            sender,
            f"Sorry, no doctors are currently available in {get_department(department).get('label', department)}. "
            "Type *menu* to go back.",
            bot,
        )
        return False

    rows = [{
        "id": f"DOC_{d.id}",
        "title": f"Dr. {d.name}"[:24],
        "description": f"${d.consultation_fee:.0f} • {(d.bio or 'Specialist')[:50]}",
    } for d in doctors[:10]]

    label = get_department(department).get("label", department.title())
    await send_interactive_list(
        sender, f"{label} Doctors", f"Choose a doctor in {label}:",
        "View Doctors", [{"title": label, "rows": rows}], bot,
    )
    return True


# ──────────────────────────────────────────────────────────────────────────
# Booking entry points
# ──────────────────────────────────────────────────────────────────────────

async def _start_booking(sender, bot, db):
    enabled = get_enabled_departments_for_bot(db, bot.id)
    if not enabled:
        await send_text_message_v2(
            sender,
            "We're still setting up our doctor roster — please contact the clinic directly to book. "
            "Type *menu* for other options.",
            bot,
        )
        return {"stage": "idle"}

    if len(enabled) == 1:
        await _send_doctor_list(sender, bot, db, enabled[0])
        return {"stage": "doctor_select", "department": enabled[0]}

    await _send_department_list(sender, bot, db)
    return {"stage": "department_select"}


async def _propose_doctor(sender, bot, db, doctor_id, reasoning_intro):
    doctor = get_doctor_by_id(db, bot.id, doctor_id)
    if not doctor:
        await send_text_message_v2(sender, "Sorry, something went wrong. Type *menu* to try again.", bot)
        return {"stage": "idle"}

    msg = (
        f"{reasoning_intro}\n\n"
        f"👨‍⚕️ *Dr. {doctor.name}* ({get_department(doctor.department).get('label', doctor.department)})\n"
        f"💰 Consultation Fee: ${doctor.consultation_fee:.0f}\n\n"
        "Would you like to book with this doctor?"
    )
    await send_interactive_buttons(
        sender, msg,
        [{"id": "TRIAGE_ACCEPT", "title": "✅ Book this doctor"},
         {"id": "TRIAGE_DECLINE", "title": "🔁 See other doctors"}],
        bot,
    )
    return {"stage": "confirm_triage_doctor", "doctor_id": doctor.id, "department": doctor.department}


async def _send_appointment_pdf(sender, bot, db, appointment, intro_text):
    try:
        doctor = get_doctor_by_id(db, bot.id, appointment.doctor_id) if appointment.doctor_id else None
        file_path = generate_appointment_pdf(appointment, bot, doctor=doctor)
        await send_text_message_v2(sender, intro_text, bot)
        sent = await send_document_v2(
            sender, file_path, f"appointment_{appointment.id}.pdf", bot,
            caption=f"Appointment #{appointment.id} confirmation",
        )
        if not sent:
            logger.warning(f"[appointment] PDF send failed for appointment #{appointment.id}")
    except Exception as exc:
        logger.error(f"[appointment] PDF generation/send failed: {exc}")


async def _ask_date(sender, bot, session):
    doctor_name = ""
    if session.get("doctor_id"):
        pass  # name not strictly needed here; date prompt stays generic
    await send_text_message_v2(sender, "Please enter your preferred *Date* (e.g. Tomorrow, Monday, or Oct 25th).", bot)
    session["stage"] = "select_date"
    return session


# ──────────────────────────────────────────────────────────────────────────
# Lab report handling
# ──────────────────────────────────────────────────────────────────────────

async def _handle_document(sender, media_id, filename, bot, db, session):
    if (getattr(bot, "provider", "meta") or "meta") == "wwebjs":
        await send_text_message_v2(
            sender,
            "📄 Lab report analysis is currently only supported on our Meta WhatsApp API number. "
            "Please describe your results in text instead, or contact the clinic directly.",
            bot,
        )
        return session

    from providers.meta import MetaProvider
    provider = MetaProvider(bot)
    result = await provider.download_media(media_id)
    if not result:
        await send_text_message_v2(sender, "Sorry, I couldn't download that file. Please try again.", bot)
        return session

    content, mime_type = result
    if "pdf" not in (mime_type or "").lower() and not filename.lower().endswith(".pdf"):
        await send_text_message_v2(
            sender,
            "📄 Right now I can only read *PDF* lab reports. Please export/scan your report as a PDF and resend, "
            "or just describe the key results in text.",
            bot,
        )
        return session

    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(content))
        text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:
        logger.error(f"[appointment] PDF text extraction failed: {exc}")
        text = ""

    if not text:
        await send_text_message_v2(
            sender,
            "I received your file but couldn't read any text from it (it may be a scanned image). "
            "Please describe the key results in text instead.",
            bot,
        )
        return session

    await send_text_message_v2(sender, "📄 Got your report — analyzing now, one moment...", bot)

    doctors = get_doctors_by_bot(db, bot.id)
    result = await analyze_lab_report(text, doctors, bot, db)

    create_lab_report(
        db, bot_id=bot.id, customer_phone=sender, filename=filename,
        extracted_text_excerpt=text, department_recommended=result.get("department", ""),
        doctor_recommended_id=result.get("doctor_id"), ai_summary=result.get("summary", ""),
    )

    summary = result.get("summary") or "Thanks for sharing your report."
    doctor_id = result.get("doctor_id")
    if doctor_id:
        return await _propose_doctor(sender, bot, db, doctor_id, f"📋 *Report Summary:*\n{summary}")

    await send_text_message_v2(sender, summary, bot)
    return {"stage": "idle"}


# ──────────────────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────────────────

async def handle_flow(sender, text, bot, db):
    session = _get_session(sender, bot.id, db)
    stage = session.get("stage", "idle")
    text_clean = text.strip()
    text_lower = text_clean.lower()

    # ── Lab report upload (sentinel set by whatsapp_router.py) ─────────────
    if text_clean.startswith("__DOCUMENT__:"):
        try:
            _, media_id, filename = text_clean.split(":", 2)
        except ValueError:
            media_id, filename = "", "report.pdf"
        session = await _handle_document(sender, media_id, filename, bot, db, session)
        _save(sender, bot.id, session, db)
        return

    # ── Universal escape hatch out of any sub-flow ─────────────────────────
    if text_lower in {"menu", "main menu", "start over"}:
        session = {"stage": "idle"}
        await _send_welcome(sender, bot, db)
        _save(sender, bot.id, session, db)
        return

    if text_lower in {"doctor", "doctors", "book"} and stage == "idle":
        session = await _start_booking(sender, bot, db)
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # DEPARTMENT SELECTION
    # ══════════════════════════════════════════════════════════════════════
    if stage == "department_select":
        if text_clean == SYMPTOM_TRIAGE_ID:
            await send_text_message_v2(
                sender,
                "No problem! Please describe what's bothering you "
                "(e.g. 'tooth pain when I chew', 'want to reduce acne scars').",
                bot,
            )
            session = {"stage": "awaiting_symptom"}
        elif text_clean.startswith("DEPT_"):
            dept_slug = text_clean.replace("DEPT_", "").lower()
            if dept_slug in DEPARTMENTS:
                found = await _send_doctor_list(sender, bot, db, dept_slug)
                session = {"stage": "doctor_select", "department": dept_slug} if found else {"stage": "idle"}
            else:
                await send_text_message_v2(sender, "Please select a department from the list. Type *menu* to retry.", bot)
        else:
            await send_text_message_v2(sender, "Please choose an option from the list above, or type *menu*.", bot)
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # DOCTOR SELECTION
    # ══════════════════════════════════════════════════════════════════════
    if stage == "doctor_select":
        if text_clean.startswith("DOC_"):
            try:
                doctor_id = int(text_clean.replace("DOC_", ""))
            except ValueError:
                doctor_id = None
            doctor = get_doctor_by_id(db, bot.id, doctor_id) if doctor_id else None
            if not doctor:
                await send_text_message_v2(sender, "Please select a doctor from the list, or type *menu*.", bot)
                _save(sender, bot.id, session, db)
                return
            session = {"stage": "select_date", "doctor_id": doctor.id, "department": doctor.department,
                       "service": f"Consultation with Dr. {doctor.name}"}
            await send_text_message_v2(
                sender,
                f"Great choice! Dr. {doctor.name} — ${doctor.consultation_fee:.0f} consultation fee.\n\n"
                "Please enter your preferred *Date* (e.g. Tomorrow, Monday, or Oct 25th).",
                bot,
            )
        else:
            await send_text_message_v2(sender, "Please select a doctor from the list above, or type *menu*.", bot)
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # SYMPTOM TRIAGE
    # ══════════════════════════════════════════════════════════════════════
    if stage == "awaiting_symptom":
        doctors = get_doctors_by_bot(db, bot.id)
        result = await recommend_doctor(text_clean, doctors, bot, db)
        doctor_id = result.get("doctor_id")
        if not doctor_id:
            await send_text_message_v2(sender, "I couldn't find a matching specialist right now. Type *menu* to browse doctors directly.", bot)
            session = {"stage": "idle"}
        else:
            reasoning = result.get("reasoning") or "Based on what you described, here's a doctor who can help:"
            session = await _propose_doctor(sender, bot, db, doctor_id, f"🩺 {reasoning}")
        _save(sender, bot.id, session, db)
        return

    if stage == "confirm_triage_doctor":
        if text_clean == "TRIAGE_ACCEPT" or text_lower in {"yes", "y", "confirm", "book"}:
            session = await _ask_date(sender, bot, session)
            session["service"] = f"Consultation with recommended doctor"
            doctor = get_doctor_by_id(db, bot.id, session.get("doctor_id"))
            if doctor:
                session["service"] = f"Consultation with Dr. {doctor.name}"
        elif text_clean == "TRIAGE_DECLINE" or text_lower in {"no", "n"}:
            session = await _start_booking(sender, bot, db)
        else:
            await send_text_message_v2(sender, "Please tap *Book this doctor* or *See other doctors* above, or type *menu*.", bot)
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # BOOKING SUB-FLOW (date → time → confirm)
    # ══════════════════════════════════════════════════════════════════════
    if stage in BOOKING_STAGES:
        if text_lower == "cancel":
            await send_text_message_v2(sender, "Booking cancelled. Type *menu* to see what else I can help with.", bot)
            session = {"stage": "idle"}
            _save(sender, bot.id, session, db)
            return

        if stage == "select_date":
            session["date"] = text_clean
            await send_text_message_v2(sender, "What *Time* works best for you? (e.g. 10 AM, 2:30 PM)", bot)
            session["stage"] = "select_time"

        elif stage == "select_time":
            session["time"] = text_clean
            doctor = get_doctor_by_id(db, bot.id, session.get("doctor_id")) if session.get("doctor_id") else None
            fee_line = f"\n💰 Fee: ${doctor.consultation_fee:.0f}" if doctor else ""
            msg = (
                f"📝 *Confirm Booking:*\n"
                f"🔹 {session.get('service', 'Appointment')}\n"
                f"📅 Date: {session['date']}\n"
                f"⏰ Time: {session['time']}{fee_line}\n\n"
                "Type *Confirm* to book, or *Cancel* to abort."
            )
            await send_text_message_v2(sender, msg, bot)
            session["stage"] = "confirm"

        elif stage == "confirm":
            if "confirm" in text_lower:
                doctor = get_doctor_by_id(db, bot.id, session.get("doctor_id")) if session.get("doctor_id") else None
                appt = create_appointment(
                    db, owner_id=bot.owner_id, bot_id=bot.id, customer_phone=sender,
                    service=session.get("service", "Appointment"),
                    appointment_date=session.get("date", ""), appointment_time=session.get("time", ""),
                    department=session.get("department", ""), doctor_id=session.get("doctor_id"),
                    consultation_fee=doctor.consultation_fee if doctor else 0.0,
                )
                await _send_appointment_pdf(sender, bot, db, appt, "✅ Appointment booked! Here's your confirmation:")
                session = {"stage": "idle"}
            else:
                await send_text_message_v2(sender, "No problem — type *menu* to start again.", bot)
                session = {"stage": "idle"}

        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # CANCEL SUB-FLOW
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
                sender, bot, db, appt,
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
        session = await _start_booking(sender, bot, db)

    elif intent == "view":
        appointments = get_upcoming_appointments(db, bot.id, sender)
        if not appointments:
            await send_text_message_v2(sender, "You have no upcoming appointments. Type *book* to schedule one!", bot)
        else:
            msg = "📋 *Your Upcoming Appointments:*\n\n" + _format_appointment_list(appointments, db, bot.id)
            await send_text_message_v2(sender, msg, bot)
        session = {"stage": "idle"}

    elif intent == "cancel":
        appointments = get_upcoming_appointments(db, bot.id, sender)
        if not appointments:
            await send_text_message_v2(sender, "You have no upcoming appointments to cancel.", bot)
            session = {"stage": "idle"}
        else:
            msg = "Which appointment would you like to cancel? Reply with the number:\n\n" + _format_appointment_list(appointments, db, bot.id)
            await send_text_message_v2(sender, msg, bot)
            session = {"stage": "await_cancel_id"}

    elif intent == "reschedule":
        appointments = get_upcoming_appointments(db, bot.id, sender)
        if not appointments:
            await send_text_message_v2(sender, "You have no upcoming appointments to reschedule.", bot)
            session = {"stage": "idle"}
        else:
            msg = "Which appointment would you like to reschedule? Reply with the number:\n\n" + _format_appointment_list(appointments, db, bot.id)
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
