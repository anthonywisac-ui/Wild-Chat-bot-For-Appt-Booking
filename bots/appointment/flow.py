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

import asyncio
import logging
import re

from db import (
    get_session_data, save_session_data,
    create_appointment, get_upcoming_appointments, get_appointment_by_id,
    cancel_appointment, reschedule_appointment,
    get_doctors_by_bot, get_doctors_by_department, get_doctor_by_id,
    get_enabled_departments_for_bot, create_lab_report,
    get_procedures_by_department, get_procedure_by_id,
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
from utils_datetime import (
    normalize_and_validate, parse_date, parse_time,
    check_doctor_shift, check_slot_conflict, format_date, format_time,
)
from ai.intent import looks_like_question
from bots.appointment.departments import DEPARTMENTS, get_department
from datetime import datetime as _datetime

logger = logging.getLogger(__name__)

BOOKING_STAGES = {"select_date", "select_time", "confirm"}
SYMPTOM_TRIAGE_ID = "SYMPTOM_TRIAGE"
PROC_SKIP_ID = "PROC_SKIP"

# Per-(bot, sender) locks so two messages arriving close together (e.g. a user
# double-tapping send) can't read-modify-write the same session state and
# silently undo each other's progress.
_session_locks: dict[tuple, asyncio.Lock] = {}
_MAX_TRACKED_LOCKS = 50_000


# Casual greetings/small-talk mid-booking ("Hi", "hello there", "how are you")
# — matched only when the WHOLE message is just chit-chat, so it never
# swallows a real date/time/question.
_CASUAL_GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|yo|good\s*(morning|afternoon|evening)|how\s*are\s*you|"
    r"how('?s| is) it going|what'?s up)[\s!.?]*$"
)


def _escape_hint(fail_count: int) -> str:
    """After repeated failures in the same step, remind the user they're never stuck."""
    if fail_count >= 2:
        return "\n\n💡 You can type *menu* anytime to start over, or just ask me a question directly."
    return ""


def _get_session_lock(bot_id, sender) -> asyncio.Lock:
    key = (bot_id, sender)
    if key not in _session_locks:
        if len(_session_locks) > _MAX_TRACKED_LOCKS:
            for stale_key, stale_lock in list(_session_locks.items()):
                if not stale_lock.locked():
                    del _session_locks[stale_key]
        _session_locks[key] = asyncio.Lock()
    return _session_locks[key]


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


async def _send_procedure_list(sender, bot, db, department: str):
    """Shows the department's bookable procedures (with sessions + fee). Returns True if any exist."""
    procedures = get_procedures_by_department(db, bot.id, department)
    if not procedures:
        return False

    rows = [{
        "id": f"PROC_{p.id}",
        "title": p.name[:24],
        "description": f"${p.fee_per_session:.0f}/session × {p.sessions_required} • {(p.description or '')[:40]}",
    } for p in procedures[:9]]
    rows.append({"id": PROC_SKIP_ID, "title": "Just a general consultation", "description": "Skip — book consultation only"})

    label = get_department(department).get("label", department.title())
    await send_interactive_list(
        sender, f"{label} Procedures", "Which treatment would you like to book?",
        "View Procedures", [{"title": "Procedures", "rows": rows}], bot,
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
    """Public entry point — serializes concurrent messages from the same sender
    so rapid double-sends can't race on the session state."""
    async with _get_session_lock(bot.id, sender):
        await _handle_flow_inner(sender, text, bot, db)


async def _handle_flow_inner(sender, text, bot, db):
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
            session = {"doctor_id": doctor.id, "department": doctor.department,
                       "service": f"Consultation with Dr. {doctor.name}",
                       "total_fee": doctor.consultation_fee}
            await send_text_message_v2(
                sender, f"Great choice! Dr. {doctor.name} — ${doctor.consultation_fee:.0f} consultation fee.", bot,
            )
            has_procedures = await _send_procedure_list(sender, bot, db, doctor.department)
            if has_procedures:
                session["stage"] = "procedure_select"
            else:
                session = await _ask_date(sender, bot, session)
        else:
            await send_text_message_v2(sender, "Please select a doctor from the list above, or type *menu*.", bot)
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # PROCEDURE SELECTION (sessions, fee, upsell)
    # ══════════════════════════════════════════════════════════════════════
    if stage == "procedure_select":
        if text_clean == PROC_SKIP_ID:
            session = await _ask_date(sender, bot, session)
        elif text_clean.startswith("PROC_"):
            try:
                procedure_id = int(text_clean.replace("PROC_", ""))
            except ValueError:
                procedure_id = None
            procedure = get_procedure_by_id(db, bot.id, procedure_id) if procedure_id else None
            if not procedure:
                await send_text_message_v2(sender, "Please select a procedure from the list, or type *menu*.", bot)
                _save(sender, bot.id, session, db)
                return

            total = procedure.fee_per_session * procedure.sessions_required
            session["procedure_id"] = procedure.id
            session["service"] = f"{procedure.name} with Dr. " + (
                get_doctor_by_id(db, bot.id, session.get("doctor_id")).name if session.get("doctor_id") else ""
            )
            session["total_fee"] = total

            sessions_note = f" ({procedure.sessions_required} sessions)" if procedure.sessions_required > 1 else ""
            await send_text_message_v2(
                sender, f"✅ {procedure.name} selected{sessions_note} — total ${total:.0f}.", bot,
            )

            import json as _json
            upsell_names = _json.loads(procedure.upsell_with_json or "[]")
            upsell_procs = []
            if upsell_names:
                dept_procs = get_procedures_by_department(db, bot.id, procedure.department)
                upsell_procs = [p for p in dept_procs if p.name in upsell_names][:2]

            if upsell_procs:
                buttons = [{"id": f"UPSELL_{p.id}", "title": f"+ {p.name[:18]}"} for p in upsell_procs]
                buttons.append({"id": "NO_UPSELL", "title": "No thanks"})
                lines = "\n".join(f"• {p.name} — ${p.fee_per_session * p.sessions_required:.0f}" for p in upsell_procs)
                await send_interactive_buttons(
                    sender,
                    f"💡 Many patients combine *{procedure.name}* with:\n{lines}\n\nWould you like to add one?",
                    buttons, bot,
                )
                session["stage"] = "upsell_offer"
                session["_upsell_options"] = {f"UPSELL_{p.id}": p.id for p in upsell_procs}
            else:
                session = await _ask_date(sender, bot, session)
        else:
            await send_text_message_v2(sender, "Please select an option from the list above, or type *menu*.", bot)
        _save(sender, bot.id, session, db)
        return

    # ══════════════════════════════════════════════════════════════════════
    # UPSELL OFFER
    # ══════════════════════════════════════════════════════════════════════
    if stage == "upsell_offer":
        options = session.get("_upsell_options", {})
        if text_clean in options:
            addon = get_procedure_by_id(db, bot.id, options[text_clean])
            if addon:
                addon_fee = addon.fee_per_session * addon.sessions_required
                session["total_fee"] = session.get("total_fee", 0.0) + addon_fee
                session["service"] = f"{session.get('service', 'Appointment')} + {addon.name}"
                await send_text_message_v2(sender, f"✅ Added {addon.name} (+${addon_fee:.0f}).", bot)
            session.pop("_upsell_options", None)
            session = await _ask_date(sender, bot, session)
        elif text_clean == "NO_UPSELL" or text_lower in {"no", "no thanks", "n"}:
            session.pop("_upsell_options", None)
            session = await _ask_date(sender, bot, session)
        else:
            await send_text_message_v2(sender, "Please tap one of the options above, or type *menu*.", bot)
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
            doctor = get_doctor_by_id(db, bot.id, session.get("doctor_id"))
            session["service"] = f"Consultation with Dr. {doctor.name}" if doctor else "Consultation"
            session["total_fee"] = doctor.consultation_fee if doctor else 0.0
            has_procedures = await _send_procedure_list(sender, bot, db, session.get("department", ""))
            session["stage"] = "procedure_select" if has_procedures else None
            if not has_procedures:
                session = await _ask_date(sender, bot, session)
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

        # Casual greetings mid-booking ("Hi", "Hello", "how are you") get a warm,
        # human reply instead of a confusing parse error — then we just repeat
        # whatever we were waiting for.
        if stage in ("select_date", "select_time") and _CASUAL_GREETING_RE.match(text_lower):
            nudge = "What *Date* would you like?" if stage == "select_date" else "And what *Time* works best for you?"
            await send_text_message_v2(sender, f"Hello! 😊 {nudge}", bot)
            _save(sender, bot.id, session, db)
            return

        # Mid-flow questions ("what's your address?", "how much is it?") get answered
        # without losing booking progress — instead of being blindly treated as a date/time.
        if stage in ("select_date", "select_time") and looks_like_question(text_clean):
            answer = await answer_with_rag(text_clean, bot, db) or await get_ai_response(sender, text_clean, bot, db)
            await send_text_message_v2(sender, answer, bot)
            follow_up = "Now, what *Date* would you like?" if stage == "select_date" else "Now, what *Time* works best for you?"
            await send_text_message_v2(sender, follow_up, bot)
            session["_fail_count"] = 0
            _save(sender, bot.id, session, db)
            return

        if stage == "select_date":
            parsed_date = parse_date(text_clean)
            if not parsed_date:
                session["_fail_count"] = session.get("_fail_count", 0) + 1
                hint = _escape_hint(session["_fail_count"])
                await send_text_message_v2(
                    sender,
                    f"I couldn't understand that date. Please try again (e.g. 'Tomorrow', 'Monday', 'Oct 25').{hint}",
                    bot,
                )
                _save(sender, bot.id, session, db)
                return

            session["date"] = parsed_date.strftime("%Y-%m-%d")
            session["_fail_count"] = 0
            await send_text_message_v2(sender, "What *Time* works best for you? (e.g. 10 AM, 2:30 PM)", bot)
            session["stage"] = "select_time"

        elif stage == "select_time":
            parsed_time = parse_time(text_clean)
            if not parsed_time:
                session["_fail_count"] = session.get("_fail_count", 0) + 1
                hint = _escape_hint(session["_fail_count"])
                await send_text_message_v2(
                    sender,
                    f"I couldn't understand that time. Please try again (e.g. '10 AM', '2:30 PM', 'afternoon').{hint}",
                    bot,
                )
                _save(sender, bot.id, session, db)
                return
            session["_fail_count"] = 0

            doctor = get_doctor_by_id(db, bot.id, session.get("doctor_id")) if session.get("doctor_id") else None
            appt_date_obj = _datetime.strptime(session["date"], "%Y-%m-%d").date()

            if doctor:
                available, shift_msg = check_doctor_shift(doctor, appt_date_obj, parsed_time)
                if not available:
                    await send_text_message_v2(sender, f"⚠️ {shift_msg}\n\nWhat *Date* would you like instead?", bot)
                    session["stage"] = "select_date"
                    session.pop("date", None)
                    _save(sender, bot.id, session, db)
                    return

                time_str = parsed_time.strftime("%H:%M")
                conflict, conflict_msg = check_slot_conflict(db, bot.id, doctor.id, session["date"], time_str)
                if conflict:
                    await send_text_message_v2(sender, f"⚠️ {conflict_msg} What other time works for you?", bot)
                    _save(sender, bot.id, session, db)
                    return

            session["time"] = parsed_time.strftime("%H:%M")
            fee = session.get("total_fee", doctor.consultation_fee if doctor else 0.0)
            fee_line = f"\n💰 Fee: ${fee:.0f}" if fee else ""
            msg = (
                f"📝 *Confirm Booking:*\n"
                f"🔹 {session.get('service', 'Appointment')}\n"
                f"📅 Date: {format_date(appt_date_obj)}\n"
                f"⏰ Time: {format_time(parsed_time)}{fee_line}\n\n"
                "Type *Confirm* to book, or *Cancel* to abort."
            )
            await send_text_message_v2(sender, msg, bot)
            session["stage"] = "confirm"

        elif stage == "confirm":
            if "confirm" in text_lower:
                doctor = get_doctor_by_id(db, bot.id, session.get("doctor_id")) if session.get("doctor_id") else None
                # Re-check the slot wasn't taken by someone else between confirm screen and now.
                if doctor:
                    validation = normalize_and_validate(db, bot.id, doctor, session.get("date", ""), session.get("time", ""))
                    if not validation["ok"]:
                        await send_text_message_v2(sender, f"⚠️ {validation['error']} Type *menu* to start again.", bot)
                        session = {"stage": "idle"}
                        _save(sender, bot.id, session, db)
                        return

                appt = create_appointment(
                    db, owner_id=bot.owner_id, bot_id=bot.id, customer_phone=sender,
                    service=session.get("service", "Appointment"),
                    appointment_date=session.get("date", ""), appointment_time=session.get("time", ""),
                    department=session.get("department", ""), doctor_id=session.get("doctor_id"),
                    consultation_fee=session.get("total_fee", doctor.consultation_fee if doctor else 0.0),
                    procedure_id=session.get("procedure_id"),
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
