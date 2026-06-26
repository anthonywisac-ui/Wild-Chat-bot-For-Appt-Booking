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
import os
import re

from db import (
    get_doctors_by_bot, get_procedures_by_bot, get_doctor_by_id, get_procedure_by_id,
    get_procedures_by_department, get_departments_with_procedures, log_bot_event,
    create_treatment_sessions, get_treatment_schedule, get_patient_profile,
    get_doctors_by_department,
)
from whatsapp_handlers import (
    send_text_message_v2, send_document_v2, send_image_v2,
    send_interactive_list, send_interactive_buttons,
)
from utils_pdf import generate_appointment_pdf

IMAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static_images")


def _image_path(name: str) -> str:
    """Looks up a brand image by base name, trying common extensions —
    admins drop files with whatever extension they were exported with."""
    base, given_ext = os.path.splitext(name)
    candidates = [given_ext] if given_ext else []
    candidates += [".png", ".jpg", ".jpeg", ".webp"]
    for ext in candidates:
        path = os.path.join(IMAGES_DIR, base + ext)
        if os.path.isfile(path):
            return path
    return os.path.join(IMAGES_DIR, name)


# Explicit filenames for department icons. NOTE: do not rely on a bare
# f"{department}.png" lookup matching an uploaded "Skin.png"/"Hair.png"/etc —
# Windows filesystems are case-insensitive so a same-named lowercase copy
# never actually became a distinct file on disk, and git only committed the
# original capitalized name. On Railway's case-sensitive Linux filesystem the
# lowercase lookup then silently finds nothing. These filenames are genuinely
# distinct files (not case-renamed copies) so they exist correctly everywhere.
_DEPARTMENT_IMAGE_FILES = {
    "skin": "skin_dept.png",
    "hair": "hair_dept.png",
    "laser": "laser_dept.png",
    "body": "body_dept.png",
    "injectables": "injectables.png",
    "dental": "dental.jpeg",
}

# Keyword -> image file for individual treatments the clinic has uploaded a
# dedicated photo for. Falls back to no image (just text) when no keyword matches.
_PROCEDURE_IMAGE_KEYWORDS = [
    ("hifu", "Hifu.png"),
    ("root canal", "Root-Canal.jpeg"),
    ("whitening", "White-Polishing.png"),
    ("polishing", "White-Polishing.png"),
]

# Per-question images for the patient-detail/intake screening flow. Any
# question key not listed here falls back to the generic question image.
_INTAKE_QUESTION_IMAGES = {
    "age": "Whats-your-age.png",
    "gender": "Whats-your-gender.png",
    "concern": "whats-your-main-skin-concern.png",
    "skin_duration": "how-long-you-had-concern.png",
    "hair_duration": "how-long-you-had-concern.png",
    "skin_type": "whats-your-skin-type.png",
}
_GENERIC_QUESTION_IMAGE = "for-All-Questions-i-ask.png"


def _question_image(field: str) -> str:
    return _image_path(_INTAKE_QUESTION_IMAGES.get(field, _GENERIC_QUESTION_IMAGE))


def _procedure_image(name: str) -> str | None:
    lowered = (name or "").lower()
    for keyword, filename in _PROCEDURE_IMAGE_KEYWORDS:
        if keyword in lowered:
            path = _image_path(filename)
            if os.path.isfile(path):
                return path
    return None

from ai.intent import looks_like_question
from bots.appointment.departments import DEPARTMENTS
from bots.appointment.intake_questions import INTAKE_QUESTIONS, ALL_INTAKE_KEYS, next_intake_question


def _set_procedure(memory: dict, proc) -> None:
    """Sets the chosen procedure on memory. If this is a DIFFERENT procedure
    than whatever was there before, clears every intake-question field across
    ALL departments first — otherwise a patient who browses, say, Body
    Treatments and then switches to Lip Fillers keeps body's stale answers
    (e.g. 'concern'/'treatment_area') and the wrong department's questions
    get silently skipped or shown with the wrong options."""
    if memory.get("procedure_id") and memory.get("procedure_id") != proc.id:
        for key in ALL_INTAKE_KEYS:
            memory[key] = None
    memory["procedure_id"] = proc.id
    memory["treatment"] = proc.name
    memory["department"] = proc.department
    memory["fee_estimate"] = proc.fee_per_session * proc.sessions_required

from bots.appointment.services import conversation_memory as memory_store
from bots.appointment.services import intent_classifier
from bots.appointment.services import appointment_service
from bots.appointment.services import knowledge_service
from bots.appointment.services import response_composer

logger = logging.getLogger(__name__)

_AFFIRMATIVE_RE = re.compile(r"^(yes|yep|yeah|confirm|sure|ok(ay)?|sounds good|go ahead|book it)\b", re.IGNORECASE)
_NEGATIVE_RE = re.compile(r"^(no|nope|not yet|cancel|wait|hold on|change)\b", re.IGNORECASE)
_CASUAL_GREETING_RE = re.compile(
    r"^(hi+|hello+|hey+|salam\w*|assalam\w*|yo|ok(ay)?|hmm+|good\s*(morning|afternoon|evening))[\s!.?]*$",
    re.IGNORECASE,
)
_DATE_HINT_RE = re.compile(
    r"\d|today|tomorrow|tonight|mon|tue|wed|thu|fri|sat|sun|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|next\s*week",
    re.IGNORECASE,
)
_TIME_HINT_RE = re.compile(
    r"\d|morning|afternoon|evening|noon|midnight|am\b|pm\b",
    re.IGNORECASE,
)


def _looks_date_like(text: str) -> bool:
    return bool(_DATE_HINT_RE.search(text))


def _looks_time_like(text: str) -> bool:
    return bool(_TIME_HINT_RE.search(text))
# Fields whose answer is just stored verbatim — no parsing needed (date/time get
# their own normalization elsewhere).
_CANCEL_BTN_RE = re.compile(r"^CANCEL_(\d+)$")
_RESCHED_BTN_RE = re.compile(r"^RESCHED_(\d+)$")
_PROC_BTN_RE = re.compile(r"^PROC_(\d+)$")
_DOC_BTN_RE = re.compile(r"^DOC_(\d+)$")
_DEPT_BTN_RE = re.compile(r"^DEPT_(\w+)$")
_UPSELL_ADD_RE = re.compile(r"^UPSELL_ADD_(\d+)$")
UPSELL_SKIP_ID = "UPSELL_SKIP"
_ENQ_BOOK_RE = re.compile(r"^ENQ_BOOK_(\d+)$")
ENQ_BROWSE_ID = "ENQ_BROWSE"
_QUICKDATE_RE = re.compile(r"^QUICKDATE_(\d{4}-\d{2}-\d{2})$")
_QUICKTIME_RE = re.compile(r"^QUICKTIME_(.+)$")

# Booking-mode patient-info questions are FIXED text, never AI-composed —
# "Book Appointment" mode must never drift into open-ended AI consultation.
_FIELD_QUESTIONS = {
    "patient_name": "What's your full name?",
    "age": "What's your age?",
    "gender": "What's your gender?",
    "allergies": "Do you have any allergies?",
    "medical_conditions": "Any medical conditions we should know about?",
    "pregnancy_status": "Are you currently pregnant or breastfeeding?",
    "current_medications": "Are you currently taking any medications?",
}

# Binary/choice screening fields get real buttons instead of free text.
_SCREEN_OPTIONS = {
    "gender": [("male", "Male"), ("female", "Female")],
    "allergies": [("none", "None"), ("yes", "Yes")],
    "medical_conditions": [("none", "None"), ("yes", "Yes")],
    "pregnancy_status": [("no", "No"), ("yes", "Yes")],
    "current_medications": [("none", "None"), ("yes", "Yes")],
}
# Tapping "Yes" on these asks a quick free-text follow-up to specify what.
_SCREEN_NEEDS_DETAIL = {"allergies", "medical_conditions", "current_medications"}
_SCREEN_BTN_RE = re.compile(r"^SCREEN_(\w+)_(\w+)$")
_INTAKE_SKIP_RE = re.compile(r"^INTAKE_SKIP_(\w+)$")
_INTAKE_YES_RE = re.compile(r"^INTAKE_YES_(\w+)$")
_INTAKE_BTN_RE = re.compile(r"^INTAKE_(\w+)_(\w+)$")

BOOKING_CONFIRM_ID = "BOOKING_CONFIRM"
BOOKING_CHANGE_ID = "BOOKING_CHANGE"
QUICK_CONSULT_ID = "QUICK_CONSULT"
QUICK_ENQUIRY_ID = "QUICK_ENQUIRY"
QUICK_BOOK_ID = "QUICK_BOOK"
RETURN_BOOK_ID = "RETURN_BOOK"
RETURN_VIEW_ID = "RETURN_VIEW"
RETURN_RESCHEDULE_ID = "RETURN_RESCHEDULE"
RETURN_CANCEL_ID = "RETURN_CANCEL"
RETURN_ASK_ID = "RETURN_ASK"


async def _send(sender, text, bot):
    await send_text_message_v2(sender, text, bot)


async def _send_with_image(sender, bot, image_name: str, text: str) -> None:
    """Sends text with a local image embedded as its caption (one message).
    Falls back to plain text if the image file doesn't exist, so a missing
    brand asset never silently drops the message entirely."""
    sent = await send_image_v2(sender, _image_path(image_name), bot, caption=text)
    if not sent:
        await _send(sender, text, bot)


async def _send_welcome_buttons(sender, bot, lead_in: str) -> None:
    """Sends the 3-button main menu with the branded welcome banner image (if
    the clinic has uploaded one) embedded as the message's own image header."""
    await send_interactive_buttons(
        sender, lead_in,
        [
            {"id": QUICK_CONSULT_ID, "title": "Consult with AI"},
            {"id": QUICK_ENQUIRY_ID, "title": "Treatment Enquiry"},
            {"id": QUICK_BOOK_ID, "title": "Book Appointment"},
        ],
        bot, image_path=_image_path("welcome_banner.png"),
    )


async def _send_returning_customer_menu(sender, bot) -> None:
    rows = [
        {"id": RETURN_BOOK_ID, "title": "Book", "description": "Book a new appointment"},
        {"id": RETURN_VIEW_ID, "title": "View", "description": "View your appointments"},
        {"id": RETURN_RESCHEDULE_ID, "title": "Reschedule", "description": "Reschedule an appointment"},
        {"id": RETURN_CANCEL_ID, "title": "Cancel", "description": "Cancel an appointment"},
        {"id": RETURN_ASK_ID, "title": "Ask a question", "description": "Hours, location, pricing..."},
    ]
    await send_interactive_list(
        sender, "Returning Customer", "I can help you:", "Select an option",
        [{"title": "Options", "rows": rows}], bot,
    )


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


# ──────────────────────────────────────────────────────────────────────────
# Structured browsing — used by Treatment Enquiry (mode="enquiry") and
# Book Appointment (mode="booking"). Buttons/lists ONLY, never an open AI
# question, per the strict per-mode UX rules.
# ──────────────────────────────────────────────────────────────────────────

async def _send_treatment_list_for_department(sender, bot, db, department: str) -> bool:
    procs = get_procedures_by_department(db, bot.id, department)
    if not procs:
        await _send(sender, f"No treatments are listed yet for {DEPARTMENTS.get(department, {}).get('label', department)}.", bot)
        return False

    rows = []
    for p in procs[:10]:
        tier = f" ({p.package_tier})" if p.package_tier else ""
        sessions = f" x{p.sessions_required}" if p.sessions_required > 1 else ""
        rows.append({
            "id": f"PROC_{p.id}", "title": f"{p.name}{tier}"[:24],
            "description": f"${p.fee_per_session:.0f}/session{sessions}",
        })
    label = DEPARTMENTS.get(department, {}).get("label", department.title())
    await send_interactive_list(
        sender, f"{label} Treatments", f"Choose a treatment in {label}:",
        "View Treatments", [{"title": "Treatments", "rows": rows}], bot,
        image_path=_image_path(_DEPARTMENT_IMAGE_FILES.get(department, f"{department}.png")),
    )
    return True


async def _send_treatment_browser(sender, bot, db, memory: dict) -> None:
    """Entry point for both Enquiry and Booking modes — Department List (if needed)
    then Treatment List. Never asks an open question."""
    enabled = get_departments_with_procedures(db, bot.id)
    if memory.get("locked_group") == "aesthetic":
        enabled = [d for d in enabled if d != "dental"]
    if not enabled:
        await _send(sender, "We're still setting up our treatment list — please contact the clinic directly.", bot)
        memory["pending_question"] = None
        memory["pending_field"] = None
        return

    department = memory.get("locked_department") or memory.get("department")
    if department and memory.get("locked_group") == "aesthetic" and department == "dental":
        department = None  # ignore a stale dental selection while aesthetic-only is locked
    if not department and len(enabled) == 1:
        department = enabled[0]

    if not department:
        rows = [{
            "id": f"DEPT_{slug.upper()}", "title": f"{info['emoji']} {info['label']}"[:24],
            "description": info["description"][:72],
        } for slug, info in DEPARTMENTS.items() if slug in enabled]
        await send_interactive_list(
            sender, "Choose a Category", "Which category are you interested in?",
            "View Categories", [{"title": "Categories", "rows": rows}], bot,
            image_path=_image_path("categories_showcase.png"),
        )
        memory["pending_question"] = "awaiting_department_choice"
        memory["pending_field"] = None
        return

    memory["department"] = department
    found = await _send_treatment_list_for_department(sender, bot, db, department)
    memory["pending_question"] = "awaiting_procedure_choice" if found else None
    memory["pending_field"] = None


async def _send_enquiry_details(sender, bot, db, memory: dict, proc) -> None:
    """Mode 2 (Treatment Enquiry) final step: Service Details + Upsell + Package
    Summary, all as deterministic text/buttons — no AI-authored answer."""
    lines = [f"*{proc.name}*"]
    if proc.package_tier:
        lines.append(f"Package: {proc.package_tier}")
    lines.append(f"Sessions: {proc.sessions_required}")
    lines.append(f"Fee: ${proc.fee_per_session:.0f}/session (total ${proc.fee_per_session * proc.sessions_required:.0f})")
    if proc.description:
        lines.append(proc.description)

    # The upsell offer itself (with Add/No thanks buttons) is shown right after
    # tapping "Book This" — showing the same combo preview here too is redundant
    # and confuses patients into thinking it's a second, different question.

    await send_interactive_buttons(
        sender, "\n".join(lines),
        [{"id": f"ENQ_BOOK_{proc.id}", "title": "Book This"}, {"id": ENQ_BROWSE_ID, "title": "Browse More"}],
        bot, image_path=_procedure_image(proc.name),
    )
    memory["pending_question"] = "awaiting_enquiry_action"
    memory["pending_field"] = None


async def _send_quick_date_picker(sender, bot, memory: dict) -> None:
    from datetime import datetime, timedelta
    today = datetime.now()
    choices = [(today, "Today"), (today + timedelta(days=1), "Tomorrow"), (today + timedelta(days=2), None)]
    buttons = []
    for d, label in choices:
        title = label or d.strftime("%A")
        buttons.append({"id": f"QUICKDATE_{d.strftime('%Y-%m-%d')}", "title": title})
    await send_interactive_buttons(sender, "What date works for you?", buttons, bot)
    memory["pending_field"] = "date"
    memory["pending_question"] = "awaiting_date_pick"


async def _send_quick_time_picker(sender, bot, memory: dict) -> None:
    buttons = [{"id": f"QUICKTIME_{t}", "title": t} for t in ["10:00 AM", "12:30 PM", "4:00 PM"]]
    await send_interactive_buttons(sender, "What time works for you?", buttons, bot)
    memory["pending_field"] = "time"
    memory["pending_question"] = "awaiting_time_pick"


async def _send_screening_buttons(sender, bot, memory: dict, field: str) -> None:
    options = _SCREEN_OPTIONS[field]
    buttons = [{"id": f"SCREEN_{field}_{val}", "title": label[:20]} for val, label in options]
    await send_interactive_buttons(sender, _FIELD_QUESTIONS[field], buttons, bot, image_path=_question_image(field))
    memory["pending_field"] = field
    memory["pending_question"] = f"awaiting_screen_{field}"


async def _send_intake_question(sender, bot, memory: dict, q: dict) -> None:
    """Sends one category-specific patient intake question (see intake_questions.py)
    as buttons, a list, or free text with a Skip option — deterministic, no AI."""
    key = q["key"]
    image_path = _question_image(key)
    if q["type"] == "buttons":
        buttons = [{"id": f"INTAKE_{key}_{val}", "title": label[:20]} for val, label in q["options"]]
        await send_interactive_buttons(sender, q["question"], buttons, bot, image_path=image_path)
    elif q["type"] == "list":
        rows = [{"id": f"INTAKE_{key}_{val}", "title": label[:24]} for val, label in q["options"]]
        await send_interactive_list(sender, "Choose one", q["question"], "Select", [{"title": "Options", "rows": rows}], bot, image_path=image_path)
    else:  # text_or_skip
        await send_interactive_buttons(
            sender, q["question"],
            [{"id": f"INTAKE_SKIP_{key}", "title": "Skip / None"}, {"id": f"INTAKE_YES_{key}", "title": "Yes"}],
            bot, image_path=image_path,
        )
    memory["pending_field"] = key
    memory["pending_question"] = f"awaiting_intake_{key}"


async def _handle_booking_intent(sender, memory: dict, bot, db) -> str | None:
    memory["pending_field"] = None  # cleared here, re-set below only if we end up asking for one
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
        if memory.get("mode") == "booking" and not memory.get("_doctor_choice_asked"):
            memory["_doctor_choice_asked"] = True
            await send_interactive_buttons(
                sender, "Preferred doctor?",
                [{"id": "DOCTOR_ANY", "title": "Any doctor"}, {"id": "DOCTOR_SELECT", "title": "Select doctor"}],
                bot,
            )
            memory["pending_question"] = "awaiting_doctor_mode_choice"
            return None

        rows = [{
            "id": f"DOC_{d.id}", "title": f"Dr. {d.name}"[:24],
            "description": f"${d.consultation_fee:.0f} • {(d.bio or 'Specialist')[:50]}",
        } for d in validation["doctor_options"][:10]]
        await send_interactive_list(
            sender, "Choose a Doctor", "Which doctor would you prefer?",
            "View Doctors", [{"title": "Doctors", "rows": rows}], bot,
            image_path=_image_path("doctor_selection.png"),
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
                sender, f"Many clients combine this with:\n{lines}\n\nWould you like to add one?",
                buttons, bot,
            )
            memory["pending_question"] = "awaiting_upsell_choice"
            return None

    if validation["blocking_error"]:
        if memory.get("mode") == "booking":
            # Mode 3 rule: no AI call, and the next reply MUST be captured
            # deterministically — otherwise a bare reply like "Monday" can get
            # misclassified as wanting to reschedule an unrelated appointment.
            await _send(sender, f"{validation['blocking_error']}", bot)
            if memory.get("date_text") or memory.get("date_iso"):
                await _send_quick_time_picker(sender, bot, memory)
            else:
                await _send_quick_date_picker(sender, bot, memory)
            return None

        directive = (
            f"The patient's requested date/time doesn't work: {validation['blocking_error']} "
            "Apologize briefly and ask for an alternative."
        )
        memory["pending_question"] = directive
        memory["pending_field"] = "date" if not (memory.get("date_text") or memory.get("date_iso")) else "time"
        return await response_composer.compose(directive, memory, bot, db)

    if validation["missing"]:
        next_field = validation["missing"][0]

        if memory.get("mode") == "booking":
            # Mode 3 rule: buttons/lists/fixed text only — never an open AI question.
            if next_field == "treatment":
                await _send_treatment_browser(sender, bot, db, memory)
                return None
            if next_field == "date":
                await _send_quick_date_picker(sender, bot, memory)
                return None
            if next_field == "time":
                await _send_quick_time_picker(sender, bot, memory)
                return None
            if next_field == "gender" and next_field in _SCREEN_OPTIONS:
                await _send_screening_buttons(sender, bot, memory, next_field)
                return None
            intake_q = next_intake_question(memory.get("department"), memory)
            if intake_q and intake_q["key"] == next_field:
                # Category-specific phrasing (intake_questions.py) takes priority
                # over the generic Yes/No screening text for any overlapping key.
                await _send_intake_question(sender, bot, memory, intake_q)
                return None
            if next_field == "phone_confirm":
                await send_interactive_buttons(
                    sender, f"Use this WhatsApp number ({sender}) for your booking, or add a different number?",
                    [{"id": "PHONE_USE", "title": "Use this number"}, {"id": "PHONE_ADD", "title": "Different number"}],
                    bot,
                )
                memory["pending_question"] = "awaiting_phone_confirm"
                return None
            if next_field in _SCREEN_OPTIONS:
                await _send_screening_buttons(sender, bot, memory, next_field)
                return None
            memory["pending_field"] = next_field
            memory["pending_question"] = _FIELD_QUESTIONS.get(next_field, f"Could you share your {next_field.replace('_', ' ')}?")
            await _send_with_image(sender, bot, _INTAKE_QUESTION_IMAGES.get(next_field, _GENERIC_QUESTION_IMAGE), memory["pending_question"])
            return None

        directive = f"Ask the patient for their {next_field.replace('_', ' ')}, naturally, using everything we already know. Ask only this one thing."
        memory["pending_question"] = directive
        memory["pending_field"] = next_field
        return await response_composer.compose(directive, memory, bot, db)

    # Everything needed is known — show the summary and ask to confirm via real buttons.
    memory["awaiting_confirmation"] = True
    summary = appointment_service.booking_summary_text(memory, bot, db)
    if memory.get("mode") == "booking":
        lead_in = "Here's your appointment summary — please confirm to finalize your booking."
    else:
        lead_in = await response_composer.compose(
            "Let the patient know you have everything you need and you're about to confirm their booking. Keep it to one short sentence.",
            memory, bot, db,
        )
    await send_interactive_buttons(
        sender, f"{lead_in}\n\n*{summary}*",
        [{"id": BOOKING_CONFIRM_ID, "title": "Confirm"}, {"id": BOOKING_CHANGE_ID, "title": "Change"}],
        bot,
    )
    return None  # already sent directly


async def _finalize_booking(sender, memory: dict, bot, db) -> str:
    appt = appointment_service.finalize_booking(memory, bot, db, sender)
    doctor = get_doctor_by_id(db, bot.id, appt.doctor_id) if appt.doctor_id else None
    procedure = get_procedure_by_id(db, bot.id, appt.procedure_id) if appt.procedure_id else None

    sessions = None
    if procedure and procedure.sessions_required and procedure.sessions_required > 1:
        sessions = create_treatment_sessions(db, appt, procedure.sessions_required, interval_days=21)

    try:
        file_path = generate_appointment_pdf(appt, bot, doctor=doctor, procedure=procedure, sessions=sessions)
        await send_document_v2(
            sender, file_path, f"appointment_{appt.id}.pdf", bot,
            caption=f"Appointment #{appt.id} confirmation",
        )
    except Exception as exc:
        logger.warning(f"[conversation_engine] PDF send failed: {exc}")

    if sessions:
        await _send_with_image(sender, bot, "Package.png", _format_treatment_schedule(sessions, procedure))

    memory_store.reset_booking_fields(memory)
    memory["awaiting_confirmation"] = False
    return "You're all booked! I've sent your confirmation as a PDF above. Is there anything else I can help with?"


def _format_treatment_schedule(sessions, procedure) -> str:
    from datetime import datetime as _dt
    lines = ["*Treatment Schedule*", ""]
    for s in sessions:
        date_obj = _dt.strptime(s.appointment_date, "%Y-%m-%d")
        time_obj = _dt.strptime(s.appointment_time, "%H:%M")
        lines.append(
            f"Session {s.session_number}: {date_obj.strftime('%d %B %Y')} at "
            f"{time_obj.strftime('%I:%M %p').lstrip('0')} — {s.status}"
        )
    lines.append("")
    lines.append(f"Total Sessions: {procedure.sessions_required}")
    lines.append(f"Package Amount: ${procedure.fee_per_session * procedure.sessions_required:.0f}")
    lines.append("")
    lines.append("Future sessions are auto-scheduled — our team will confirm or adjust each one closer to the date.")
    return "\n".join(lines)


async def handle_turn(sender: str, text: str, bot, db) -> None:
    text_stripped_early = text.strip()
    lowered_early = text_stripped_early.lower()

    # ── Testing/admin shortcuts — checked before anything else, never AI-classified ──
    if lowered_early == "-reset":
        from db import reset_customer
        reset_customer(db, bot.id, sender, wipe_appointments=True)
        await _send_welcome_buttons(
            sender, bot,
            "All set — starting fresh as a new customer!\n\n"
            f"Welcome to *{bot.business_name or bot.name}*. How can we help you today?",
        )
        return

    if lowered_early in ("-aesthetic", "-ashtetic", "-esthetic", "-easthetic", "-skin", "-cosmetic", "-beauty"):
        memory = memory_store.load_memory(db, bot.id, sender)
        memory["locked_group"] = "aesthetic"  # any non-dental category (skin/hair/laser/injectables/body)
        memory["locked_department"] = None
        memory["department"] = None
        memory["pending_question"] = None
        memory["pending_field"] = None
        if memory.get("mode") in ("enquiry", "booking"):
            await _send(sender, "Got it — switching to Aesthetic & Cosmetic treatments.", bot)
            await _send_treatment_browser(sender, bot, db, memory)
        else:
            await _send(sender, "Got it — we'll keep this chat focused on Aesthetic & Cosmetic treatments only. How can I help?", bot)
        memory_store.append_history(memory, "assistant", "")
        memory_store.save_memory(db, bot.id, sender, memory)
        return

    if lowered_early == "-dental":
        memory = memory_store.load_memory(db, bot.id, sender)
        memory["locked_department"] = "dental"
        memory["locked_group"] = None
        memory["department"] = None
        memory["pending_question"] = None
        memory["pending_field"] = None
        if memory.get("mode") in ("enquiry", "booking"):
            await _send(sender, "Got it — switching to Dental treatments.", bot)
            await _send_treatment_browser(sender, bot, db, memory)
        else:
            await _send(sender, "Got it — we'll keep this chat focused on Dental treatments only. How can I help?", bot)
        memory_store.append_history(memory, "assistant", "")
        memory_store.save_memory(db, bot.id, sender, memory)
        return

    if lowered_early in ("-home", "-menu"):
        memory = memory_store.load_memory(db, bot.id, sender)
        memory["mode"] = None
        memory["department"] = None
        memory["pending_question"] = None
        memory["pending_field"] = None
        memory["awaiting_confirmation"] = False
        await _send_welcome_buttons(sender, bot, f"Welcome back to *{bot.business_name or bot.name}*. How can we help you today?")
        memory_store.append_history(memory, "assistant", "")
        memory_store.save_memory(db, bot.id, sender, memory)
        return

    if lowered_early == "-back":
        memory = memory_store.load_memory(db, bot.id, sender)
        memory["pending_question"] = None
        memory["pending_field"] = None
        if memory.get("mode") in ("enquiry", "booking"):
            memory["department"] = None
            await _send_treatment_browser(sender, bot, db, memory)
        else:
            await _send(sender, "Okay — what would you like to do instead?", bot)
        memory_store.append_history(memory, "assistant", "")
        memory_store.save_memory(db, bot.id, sender, memory)
        return

    if lowered_early == "-book":
        memory = memory_store.load_memory(db, bot.id, sender)
        memory = appointment_service.load_patient_profile(memory, bot, db, sender)
        memory["mode"] = "booking"
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    if lowered_early == "-consult":
        memory = memory_store.load_memory(db, bot.id, sender)
        memory["mode"] = "consult"
        reply = "I'd love to understand your concern and suggest the best options. What's bothering you, or what would you like to improve?"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if lowered_early == "-help":
        reply = (
            "*Available commands:*\n"
            "-reset — start fresh as a new customer\n"
            "-home / -menu — return to the main menu\n"
            "-back — go back a step\n"
            "-aesthetic / -skin / -cosmetic / -beauty — focus on Aesthetic & Cosmetic treatments\n"
            "-dental — focus on Dental treatments\n"
            "-book — start booking an appointment\n"
            "-consult — talk to the AI about your concern\n"
            "-reports — view clinic activity reports"
        )
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

        reply = "*Clinic Reports*\n\n" + "\n\n".join([
            _line("Today", daily), _line("This Week", weekly), _line("This Month", monthly),
        ])
        await _send(sender, reply, bot)
        return

    memory = memory_store.load_memory(db, bot.id, sender)
    memory = appointment_service.load_patient_profile(memory, bot, db, sender)
    memory_store.append_history(memory, "user", text)
    text_stripped = text.strip()

    # ── Welcome-screen quick actions set the MODE for the rest of this chat ──
    # Mode 1 (Consult): free-form AI conversation. Mode 2/3 (Enquiry/Booking):
    # buttons/lists only, never an open AI question — per the strict UX rules.
    if text_stripped == QUICK_CONSULT_ID:
        memory["mode"] = "consult"
        reply = "I'd love to understand your concern and suggest the best options. What's bothering you, or what would you like to improve?"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if text_stripped == QUICK_ENQUIRY_ID:
        memory["mode"] = "enquiry"
        await _send_treatment_browser(sender, bot, db, memory)
        memory_store.save_memory(db, bot.id, sender, memory)
        return

    if text_stripped == QUICK_BOOK_ID:
        memory["mode"] = "booking"
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    # ── Returning Customer menu taps ────────────────────────────────────────
    if text_stripped == RETURN_BOOK_ID:
        memory["mode"] = "booking"
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    if text_stripped == RETURN_VIEW_ID:
        appointments = appointment_service.list_upcoming(bot, db, sender)
        if not appointments:
            reply = "You have no upcoming appointments right now. Would you like to book one?"
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
        else:
            lines = [f"#{a.id} {_appointment_label(a, db, bot)} — {a.appointment_date} at {a.appointment_time}" for a in appointments]
            reply = "*Your Upcoming Appointments:*\n" + "\n".join(lines)
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
        return

    if text_stripped == RETURN_RESCHEDULE_ID:
        appointments = appointment_service.list_upcoming(bot, db, sender)
        if not appointments:
            reply = "You have no upcoming appointments to reschedule."
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
        else:
            await _send_appointment_picker(sender, bot, db, appointments, "reschedule")
            memory["pending_question"] = "awaiting_reschedule_choice"
            memory["_candidate_ids"] = [a.id for a in appointments]
            memory_store.save_memory(db, bot.id, sender, memory)
        return

    if text_stripped == RETURN_CANCEL_ID:
        appointments = appointment_service.list_upcoming(bot, db, sender)
        if not appointments:
            reply = "You have no upcoming appointments to cancel."
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
        else:
            await _send_appointment_picker(sender, bot, db, appointments, "cancel")
            memory["pending_question"] = "awaiting_cancel_choice"
            memory["_candidate_ids"] = [a.id for a in appointments]
            memory_store.save_memory(db, bot.id, sender, memory)
        return

    if text_stripped == RETURN_ASK_ID:
        reply = "Sure — what would you like to know? (hours, location, pricing, a treatment...)"
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send_with_image(sender, bot, "Customer-Ask-a-Question.png", reply)
        return

    # ── Category (department) list tap — Mode 2/3 structured browsing ──────
    dept_match = _DEPT_BTN_RE.match(text_stripped)
    if dept_match and memory.get("pending_question") == "awaiting_department_choice":
        dept_slug = dept_match.group(1).lower()
        if dept_slug in DEPARTMENTS:
            memory["department"] = dept_slug
        memory["pending_question"] = None
        found = await _send_treatment_list_for_department(sender, bot, db, memory.get("department"))
        memory["pending_question"] = "awaiting_procedure_choice" if found else None
        memory_store.save_memory(db, bot.id, sender, memory)
        return

    # ── Treatment Enquiry (Mode 2): "Book This" / "Browse More" after details ──
    enq_book_match = _ENQ_BOOK_RE.match(text_stripped)
    if enq_book_match and memory.get("pending_question") == "awaiting_enquiry_action":
        memory["mode"] = "booking"
        memory["pending_question"] = None
        proc = get_procedure_by_id(db, bot.id, int(enq_book_match.group(1)))
        if proc:
            _set_procedure(memory, proc)
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    if text_stripped == ENQ_BROWSE_ID and memory.get("pending_question") == "awaiting_enquiry_action":
        memory["department"] = None
        memory["pending_question"] = None
        await _send_treatment_browser(sender, bot, db, memory)
        memory_store.save_memory(db, bot.id, sender, memory)
        return

    # ── Quick date/time picks (Mode 3 booking only) ─────────────────────────
    quickdate_match = _QUICKDATE_RE.match(text_stripped)
    if quickdate_match and memory.get("pending_field") == "date":
        memory["date_text"] = quickdate_match.group(1)
        memory["pending_field"] = None
        memory["pending_question"] = None
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    quicktime_match = _QUICKTIME_RE.match(text_stripped)
    if quicktime_match and memory.get("pending_field") == "time":
        memory["time_text"] = quicktime_match.group(1)
        memory["pending_field"] = None
        memory["pending_question"] = None
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    # ── Screening field Yes/No/Male/Female button taps ──────────────────────
    screen_match = _SCREEN_BTN_RE.match(text_stripped)
    if screen_match and screen_match.group(1) in _SCREEN_OPTIONS and memory.get("pending_field") == screen_match.group(1):
        field, value = screen_match.group(1), screen_match.group(2)
        if value == "yes" and field in _SCREEN_NEEDS_DETAIL:
            memory["pending_question"] = f"Please specify your {field.replace('_', ' ')}."
            reply = memory["pending_question"]
        else:
            label_map = dict(_SCREEN_OPTIONS[field])
            memory[field] = label_map.get(value, value)
            memory["pending_field"] = None
            memory["pending_question"] = None
            reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    # ── Category-specific intake question taps (see intake_questions.py) ───
    intake_skip_match = _INTAKE_SKIP_RE.match(text_stripped)
    if intake_skip_match and memory.get("pending_field") == intake_skip_match.group(1):
        memory[intake_skip_match.group(1)] = "None"
        memory["pending_field"] = None
        memory["pending_question"] = None
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    intake_yes_match = _INTAKE_YES_RE.match(text_stripped)
    if intake_yes_match and memory.get("pending_field") == intake_yes_match.group(1):
        # pending_field stays the same key — the next free-text reply gets
        # captured straight into it by the generic pending_field mechanism.
        memory["pending_question"] = "Please go ahead and specify."
        reply = memory["pending_question"]
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    intake_match = _INTAKE_BTN_RE.match(text_stripped)
    if intake_match and intake_match.group(1) == memory.get("pending_field"):
        field, value = intake_match.group(1), intake_match.group(2)
        label = value
        for dept_questions in INTAKE_QUESTIONS.values():
            for q in dept_questions:
                if q["key"] == field:
                    label = dict(q["options"]).get(value, value)
                    break
        memory[field] = label
        memory["pending_field"] = None
        memory["pending_question"] = None
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
            reply = f"Your appointment #{appt.id} on {appt.appointment_date} has been cancelled."
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
                    reply = f"Your appointment #{appt.id} on {appt.appointment_date} has been cancelled."
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

    if text_stripped == "PHONE_USE" and memory.get("pending_question") == "awaiting_phone_confirm":
        memory["phone_confirmed"] = True
        memory["pending_question"] = None
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    if text_stripped == "PHONE_ADD" and memory.get("pending_question") == "awaiting_phone_confirm":
        memory["pending_field"] = "alt_phone"
        memory["pending_question"] = "Please share the number you'd like us to use."
        reply = memory["pending_question"]
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    if text_stripped in ("DOCTOR_ANY", "DOCTOR_SELECT") and memory.get("pending_question") == "awaiting_doctor_mode_choice":
        memory["pending_question"] = None
        if text_stripped == "DOCTOR_ANY":
            pool = get_doctors_by_department(db, bot.id, memory.get("department")) if memory.get("department") else get_doctors_by_bot(db, bot.id)
            if pool:
                memory["doctor_id"] = pool[0].id
        reply = await _handle_booking_intent(sender, memory, bot, db)
        memory_store.append_history(memory, "assistant", reply or "")
        memory_store.save_memory(db, bot.id, sender, memory)
        if reply:
            await _send(sender, reply, bot)
        return

    proc_match = _PROC_BTN_RE.match(text_stripped)
    doc_match = _DOC_BTN_RE.match(text_stripped)

    if proc_match and memory.get("pending_question") == "awaiting_procedure_choice":
        proc = get_procedure_by_id(db, bot.id, int(proc_match.group(1)))
        if proc:
            _set_procedure(memory, proc)
        memory["pending_question"] = None
        memory["pending_field"] = None

        if memory.get("mode") == "enquiry" and proc:
            await _send_enquiry_details(sender, bot, db, memory, proc)
            memory_store.append_history(memory, "assistant", "")
            memory_store.save_memory(db, bot.id, sender, memory)
            return

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
            gender_image = "Dr-Female.png" if (doctor.gender or "").lower() == "female" else "Dr-male.png" if (doctor.gender or "").lower() == "male" else None
            if gender_image:
                await _send_with_image(sender, bot, gender_image, f"Great choice — Dr. {doctor.name} it is!")
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
                reply = f"Your appointment #{appt.id} has been rescheduled to {temp_memory['date_iso']} at {temp_memory['time_24h']}."
                memory["pending_question"] = None
                memory["appointment_id"] = None
        memory_store.append_history(memory, "assistant", reply)
        memory_store.save_memory(db, bot.id, sender, memory)
        await _send(sender, reply, bot)
        return

    # ── Answer to a specific question we just asked — captured directly, never
    # re-classified. This is what stops a small/fast model from losing track of
    # terse answers ("Ni", "20", "Aadmi") and re-asking the same thing forever. ──
    if memory.get("pending_field"):
        if _CASUAL_GREETING_RE.match(text_stripped):
            reply = await response_composer.compose(
                memory.get("pending_question") or "Greet warmly and ask your pending question again.",
                memory, bot, db,
            )
            memory_store.append_history(memory, "assistant", reply)
            memory_store.save_memory(db, bot.id, sender, memory)
            await _send(sender, reply, bot)
            return
        if not looks_like_question(text_stripped):
            field = memory.pop("pending_field")
            # A reply that clearly doesn't look like a date/time (e.g. "None",
            # "Hu" — typically a retyped previous answer because the picker
            # buttons didn't visibly arrive) must NOT be stored as the literal
            # date_text/time_text: that corrupts the field and gets fed into
            # the AI date parser, producing nonsense like "did you mean Hour?".
            # Re-show the picker instead, in mode=="booking", keeping pending_field set.
            if field == "date" and not _looks_date_like(text_stripped) and memory.get("mode") == "booking":
                await _send_quick_date_picker(sender, bot, memory)
                memory_store.save_memory(db, bot.id, sender, memory)
                return
            if field == "time" and not _looks_time_like(text_stripped) and memory.get("mode") == "booking":
                await _send_quick_time_picker(sender, bot, memory)
                memory_store.save_memory(db, bot.id, sender, memory)
                return

            memory["pending_question"] = None
            if field == "date":
                memory["date_text"] = text_stripped
            elif field == "time":
                memory["time_text"] = text_stripped
            elif field == "alt_phone":
                memory["alt_phone"] = text_stripped
                memory["phone_confirmed"] = True
            else:
                # pending_field is always something WE set deliberately (a fixed
                # screening field or an intake_questions.py key) — safe to store
                # the literal reply directly, no whitelist needed.
                memory[field] = text_stripped
            reply = await _handle_booking_intent(sender, memory, bot, db)
            memory_store.append_history(memory, "assistant", reply or "")
            memory_store.save_memory(db, bot.id, sender, memory)
            if reply:
                await _send(sender, reply, bot)
            return
        # Looks like a genuine question — fall through to full classification so
        # it gets answered properly; pending_field stays set for next time.

    # ── Enquiry/Booking modes never drift into free-text AI consultation: if a
    # structured button prompt is pending and the reply doesn't match it, just
    # re-show the same buttons/list instead of classifying the message. ──────
    pending_q = memory.get("pending_question") or ""
    structured_states = {
        "awaiting_department_choice", "awaiting_procedure_choice", "awaiting_doctor_choice",
        "awaiting_enquiry_action", "awaiting_upsell_choice", "awaiting_date_pick", "awaiting_time_pick",
    }
    if memory.get("mode") in ("enquiry", "booking") and (pending_q in structured_states or pending_q.startswith("awaiting_screen_")):
        if pending_q == "awaiting_department_choice":
            await _send_treatment_browser(sender, bot, db, memory)
        elif pending_q == "awaiting_procedure_choice":
            await _send_treatment_list_for_department(sender, bot, db, memory.get("department"))
        elif pending_q == "awaiting_doctor_choice":
            reply = await _handle_booking_intent(sender, memory, bot, db)
            if reply:
                await _send(sender, reply, bot)
        elif pending_q == "awaiting_enquiry_action":
            await _send(sender, "Please tap *Book This* or *Browse More* above.", bot)
        elif pending_q == "awaiting_upsell_choice":
            await _send(sender, "Please tap one of the options above, or *No thanks*.", bot)
        elif pending_q == "awaiting_date_pick":
            await _send_quick_date_picker(sender, bot, memory)
        elif pending_q == "awaiting_time_pick":
            await _send_quick_time_picker(sender, bot, memory)
        elif pending_q.startswith("awaiting_screen_"):
            field = pending_q.replace("awaiting_screen_", "")
            if field in _SCREEN_OPTIONS:
                await _send_screening_buttons(sender, bot, memory, field)
        memory_store.append_history(memory, "assistant", "")
        memory_store.save_memory(db, bot.id, sender, memory)
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
        if get_patient_profile(db, bot.id, sender):
            await _send_returning_customer_menu(sender, bot)
        else:
            await _send_welcome_buttons(sender, bot, "How can we help you today?")
        reply = None

    elif intent == "appointment_booking":
        # Always lock into structured Mode 3 once genuine booking intent is
        # detected — even mid-Consult-mode conversation. Without this, a
        # patient who says "yes, book it" while mode is already "consult"
        # never actually transitions: the AI free-text-replies "I've booked
        # your appointment" without ever collecting details, validating
        # availability, or creating a real Appointment record.
        memory["mode"] = "booking"
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
                lines.append(f"#{a.id} — {_appointment_label(a, db, bot)}\n{a.appointment_date} {a.appointment_time}")
            reply = "*Your Upcoming Appointments:*\n\n" + "\n\n".join(lines)

    elif intent == "appointment_cancel":
        appointments = appointment_service.list_upcoming(bot, db, sender)
        if not appointments:
            reply = await response_composer.compose(
                "The patient wants to cancel but has no upcoming appointments. Let them know gently.", memory, bot, db,
            )
        elif len(appointments) == 1:
            appointment_service.cancel(db, appointments[0])
            reply = f"Your appointment #{appointments[0].id} on {appointments[0].appointment_date} has been cancelled."
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
                reply = f"Your appointment #{appt.id} has been rescheduled to {temp_memory['date_iso']} at {temp_memory['time_24h']}."
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
