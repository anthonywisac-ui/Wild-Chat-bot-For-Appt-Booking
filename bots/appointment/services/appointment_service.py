# bots/appointment/services/appointment_service.py
#
# Business logic layer. Takes whatever entities the conversation has accumulated
# (in any order, across any number of turns) and:
#   - resolves them against REAL clinic data (actual doctors/procedures, not guesses)
#   - validates date/time against doctor shifts and existing bookings
#   - executes the actual DB write when the patient confirms
#
# This is where "the backend acts as executor" — no LLM calls happen in this
# file except the date/time AI-assist fallback (ai/slotfill), which is itself
# re-validated deterministically before being trusted.

from __future__ import annotations

import json

from db import (
    get_doctors_by_bot, get_doctors_by_department, get_procedures_by_bot,
    get_procedures_by_department, get_doctor_by_id, get_procedure_by_id,
    create_appointment, get_upcoming_appointments, get_appointment_by_id,
    cancel_appointment, reschedule_appointment,
    get_patient_profile, upsert_patient_profile,
    upsert_lead,
)
from utils_datetime import (
    parse_date, parse_time, check_doctor_shift, check_slot_conflict,
    format_date, format_time, get_working_days_summary,
)
from ai.slotfill import interpret_date_or_time
from bots.appointment.departments import DEPARTMENTS
from datetime import datetime as _dt


# ──────────────────────────────────────────────────────────────────────────
# Matching real records against free-text entities
# ──────────────────────────────────────────────────────────────────────────

def resolve_department(memory: dict, bot, db) -> str | None:
    if memory.get("locked_department") in DEPARTMENTS:
        return memory["locked_department"]  # -aesthetic/-dental shortcut overrides everything

    if memory.get("department") in DEPARTMENTS:
        return memory["department"]

    text = " ".join(filter(None, [memory.get("treatment"), memory.get("concern")])).lower()
    if not text:
        return None

    # Match against real procedure names first (most reliable signal)
    for proc in get_procedures_by_bot(db, bot.id):
        if proc.name.lower() in text or text in proc.name.lower():
            return proc.department

    # Fall back to department descriptions (keyword-ish but based on real catalog, not guesses)
    for slug, info in DEPARTMENTS.items():
        keywords = [w.lower() for w in info["description"].replace(",", " ").split() if len(w) > 4]
        if any(kw in text for kw in keywords):
            return slug

    return None


def resolve_procedure(memory: dict, bot, db, department: str | None):
    treatment_text = (memory.get("treatment") or "").strip().lower()
    if not treatment_text:
        return None

    candidates = get_procedures_by_department(db, bot.id, department) if department else get_procedures_by_bot(db, bot.id)
    for proc in candidates:
        if proc.name.lower() in treatment_text or treatment_text in proc.name.lower():
            return proc
    return None


def resolve_doctor(memory: dict, bot, db, department: str | None):
    """Picks a doctor based on explicit preference (gender/name) when given, or
    auto-assigns when there's only one doctor to choose from. Returns None when
    genuinely ambiguous (multiple doctors, no preference) — the caller should
    then show a list instead of silently guessing who the patient wants."""
    if memory.get("doctor_id"):
        existing = get_doctor_by_id(db, bot.id, memory["doctor_id"])
        if existing:
            return existing

    pool = get_doctors_by_department(db, bot.id, department) if department else get_doctors_by_bot(db, bot.id)
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]

    preference = (memory.get("doctor_preference") or "").strip().lower()
    if preference:
        for doc in pool:
            if preference in doc.name.lower():
                return doc
        for doc in pool:
            if doc.gender and doc.gender.lower() in preference:
                return doc

    return None  # ambiguous — let the caller offer a list


def find_candidate_procedures(memory: dict, bot, db, department: str | None):
    """When the patient mentioned a treatment/concern but it doesn't uniquely match
    one procedure, returns the department's procedure list so the patient can pick —
    instead of the bot silently guessing which treatment they meant."""
    if not department:
        return []
    text = (memory.get("treatment") or memory.get("concern") or "").strip()
    if not text:
        return []
    if resolve_procedure(memory, bot, db, department):
        return []  # already matched uniquely, no ambiguity
    candidates = get_procedures_by_department(db, bot.id, department)
    return candidates if len(candidates) > 1 else []


def find_candidate_doctors(memory: dict, bot, db, department: str | None):
    """Returns the doctor list when genuinely ambiguous (multiple doctors, no
    preference given/matched) — empty otherwise."""
    if memory.get("doctor_id") or not department:
        return []
    pool = get_doctors_by_department(db, bot.id, department)
    if len(pool) <= 1:
        return []
    if resolve_doctor(memory, bot, db, department):
        return []  # preference matched uniquely
    return pool


def get_upsell_candidates(memory: dict, bot, db) -> list:
    """Returns up to 2 admin-configured complementary procedures for the patient's
    chosen treatment — used for a one-time, natural upsell offer (never forced)."""
    if not memory.get("procedure_id"):
        return []
    proc = get_procedure_by_id(db, bot.id, memory["procedure_id"])
    if not proc:
        return []
    upsell_names = json.loads(proc.upsell_with_json or "[]")
    if not upsell_names:
        return []
    dept_procs = get_procedures_by_department(db, bot.id, proc.department)
    return [p for p in dept_procs if p.name in upsell_names and p.id != proc.id][:2]


# ──────────────────────────────────────────────────────────────────────────
# Lead qualification (CRM) — captured even before any appointment is booked
# ──────────────────────────────────────────────────────────────────────────

def save_lead_snapshot(memory: dict, bot, db, sender: str, status: str = None) -> None:
    """Upserts whatever sales-relevant signals we've gathered so far. Called every
    turn so the clinic's sales team has an up-to-date follow-up list even for
    leads that never finish booking."""
    has_signal = any(memory.get(f) for f in (
        "goal", "concern", "secondary_concern", "timeline", "treatment", "budget_level", "lead_quality",
    ))
    if not has_signal:
        return

    data = {
        "goal": memory.get("goal"),
        "concern": memory.get("concern"),
        "secondary_concern": memory.get("secondary_concern"),
        "timeline": memory.get("timeline"),
        "treatment_interest": memory.get("treatment"),
        "budget_level": memory.get("budget_level"),
        "lead_quality": memory.get("lead_quality"),
        "buying_intention": memory.get("buying_intention"),
        "estimated_value": memory.get("fee_estimate"),
    }
    if status:
        data["status"] = status
    elif memory.get("treatment") or memory.get("department"):
        data["status"] = "qualified"

    try:
        upsert_lead(db, bot.id, sender, data)
    except Exception:
        pass  # CRM tracking must never break the actual conversation


# ──────────────────────────────────────────────────────────────────────────
# Patient profile (CRM) — returning patients are never re-screened
# ──────────────────────────────────────────────────────────────────────────

def load_patient_profile(memory: dict, bot, db, sender: str) -> dict:
    """Pulls any on-file medical/demographic facts into memory, once per conversation,
    so a returning patient is never asked the same screening questions again."""
    if memory.get("profile_loaded"):
        return memory

    profile = get_patient_profile(db, bot.id, sender)
    if profile:
        for field in (
            "name", "age", "gender", "city", "allergies", "medical_conditions",
            "pregnancy_status", "current_medications", "previous_treatments",
        ):
            value = getattr(profile, field, None)
            if value and not memory.get("patient_name" if field == "name" else field):
                memory["patient_name" if field == "name" else field] = value

    memory["profile_loaded"] = True
    return memory


def save_patient_profile(memory: dict, bot, db, sender: str) -> None:
    upsert_patient_profile(db, bot.id, sender, {
        "name": memory.get("patient_name"),
        "age": memory.get("age"),
        "gender": memory.get("gender"),
        "city": memory.get("city"),
        "allergies": memory.get("allergies"),
        "medical_conditions": memory.get("medical_conditions"),
        "pregnancy_status": memory.get("pregnancy_status"),
        "current_medications": memory.get("current_medications"),
        "previous_treatments": memory.get("previous_treatments"),
    })


def _required_screening_fields(department: str | None, gender: str | None = None) -> list[str]:
    """Department-agnostic identity fields, asked once before the category-specific
    intake questionnaire (see intake_questions.py) takes over for allergies, medical
    conditions, pregnancy, medications, etc. — each asked with category-appropriate
    wording instead of one generic set."""
    return ["patient_name", "age", "gender"]


# ──────────────────────────────────────────────────────────────────────────
# Entity resolution pass — called every turn while booking is in progress
# ──────────────────────────────────────────────────────────────────────────

async def resolve_and_validate(memory: dict, bot, db) -> dict:
    """
    Updates memory in-place with resolved department/procedure_id/doctor_id and,
    if both date and time are known, normalized date_iso/time_24h.

    Returns: {"missing": [...], "blocking_error": str|None, "procedure_options": [...], "doctor_options": [...]}
    blocking_error is set when a resolved date/time conflicts with the doctor's
    shift or an existing booking — the caller should surface this and clear the
    relevant memory field so the patient is asked again.
    procedure_options/doctor_options are set when there's genuine ambiguity —
    the caller should show a list and wait for a choice before continuing.
    """
    department = resolve_department(memory, bot, db)
    if department:
        memory["department"] = department

    if not memory.get("procedure_id") and memory.get("treatment"):
        proc = resolve_procedure(memory, bot, db, department)
        if proc:
            memory["procedure_id"] = proc.id
            memory["department"] = proc.department
            memory["fee_estimate"] = proc.fee_per_session * proc.sessions_required

    procedure_options = find_candidate_procedures(memory, bot, db, memory.get("department"))
    if procedure_options:
        return {"missing": [], "blocking_error": None, "procedure_options": procedure_options, "doctor_options": []}

    if not memory.get("doctor_id"):
        doctor = resolve_doctor(memory, bot, db, memory.get("department"))
        if doctor:
            memory["doctor_id"] = doctor.id
            if not memory.get("fee_estimate"):
                memory["fee_estimate"] = doctor.consultation_fee

    missing = []
    if memory.get("mode") == "booking":
        # Mode 3 always walks through the explicit Treatment List step — a vague
        # concern mentioned earlier (e.g. in Consult mode) is not enough; without a
        # real procedure_id there's no fee, no sessions, nothing to confirm.
        if not memory.get("procedure_id"):
            missing.append("treatment")
    elif not memory.get("department") and not memory.get("treatment") and not memory.get("concern"):
        missing.append("treatment")

    for field in _required_screening_fields(memory.get("department"), memory.get("gender")):
        if not memory.get(field):
            missing.append(field)

    doctor_options = []
    if not missing:
        from bots.appointment.intake_questions import next_intake_question
        next_q = next_intake_question(memory.get("department"), memory)
        if next_q:
            missing.append(next_q["key"])
        elif memory.get("mode") == "booking" and not memory.get("phone_confirmed"):
            missing.append("phone_confirm")
        else:
            # Doctor preference is asked last, right before date/time — patient
            # details and intake answers come first per the clinic's intake order.
            doctor_options = find_candidate_doctors(memory, bot, db, memory.get("department"))
            if doctor_options:
                return {"missing": [], "blocking_error": None, "procedure_options": [], "doctor_options": doctor_options}

    if not memory.get("date_text") and not memory.get("date_iso"):
        missing.append("date")
    if not memory.get("time_text") and not memory.get("time_24h"):
        missing.append("time")

    blocking_error = None
    if memory.get("date_text") and memory.get("time_text") and not (memory.get("date_iso") and memory.get("time_24h")):
        blocking_error = await normalize_date_time(memory, bot, db)

    return {"missing": missing, "blocking_error": blocking_error, "procedure_options": [], "doctor_options": []}


async def normalize_date_time(memory: dict, bot, db) -> str | None:
    """Tries to turn date_text/time_text into canonical date_iso/time_24h.
    Returns an error string (and clears the offending field) on failure."""
    parsed_date = parse_date(memory["date_text"])
    if not parsed_date:
        ai_result = await interpret_date_or_time("date", memory["date_text"], bot, db)
        if ai_result.get("extracted"):
            parsed_date = parse_date(ai_result["extracted"])
        if not parsed_date:
            memory["date_text"] = None
            return ai_result.get("reply") or "What date works best for you?"

    parsed_time = parse_time(memory["time_text"])
    if not parsed_time:
        ai_result = await interpret_date_or_time("time", memory["time_text"], bot, db)
        if ai_result.get("extracted"):
            parsed_time = parse_time(ai_result["extracted"])
        if not parsed_time:
            memory["time_text"] = None
            return ai_result.get("reply") or "What time works best for you?"

    doctor = get_doctor_by_id(db, bot.id, memory["doctor_id"]) if memory.get("doctor_id") else None
    if doctor:
        available, shift_msg = check_doctor_shift(doctor, parsed_date, parsed_time)
        if not available:
            memory["date_text"] = None
            memory["time_text"] = None
            return shift_msg

        time_str = parsed_time.strftime("%H:%M")
        date_str = parsed_date.strftime("%Y-%m-%d")
        conflict, conflict_msg = check_slot_conflict(db, bot.id, doctor.id, date_str, time_str)
        if conflict:
            memory["time_text"] = None
            return conflict_msg

    memory["date_iso"] = parsed_date.strftime("%Y-%m-%d")
    memory["time_24h"] = parsed_time.strftime("%H:%M")
    return None


def is_ready_to_confirm(memory: dict) -> bool:
    return bool(memory.get("date_iso") and memory.get("time_24h") and (memory.get("department") or memory.get("procedure_id")))


def booking_summary_text(memory: dict, bot, db) -> str:
    doctor = get_doctor_by_id(db, bot.id, memory["doctor_id"]) if memory.get("doctor_id") else None
    procedure = get_procedure_by_id(db, bot.id, memory["procedure_id"]) if memory.get("procedure_id") else None

    parts = []
    if procedure:
        parts.append(f"{procedure.name}")
    elif memory.get("treatment"):
        parts.append(memory["treatment"])
    else:
        parts.append("Consultation")
    if doctor:
        parts.append(f"with Dr. {doctor.name}")

    date_obj = _dt.strptime(memory["date_iso"], "%Y-%m-%d").date()
    time_obj = _dt.strptime(memory["time_24h"], "%H:%M").time()

    fee = memory.get("fee_estimate") or (doctor.consultation_fee if doctor else 0.0)
    sessions_line = ""
    if procedure and procedure.sessions_required and procedure.sessions_required > 1:
        sessions_line = (
            f"📦 {procedure.sessions_required} sessions (package total — first visit shown below)\n"
        )
    return (
        f"{' '.join(parts)}\n"
        f"{sessions_line}"
        f"📅 {format_date(date_obj)}\n"
        f"⏰ {format_time(time_obj)}\n"
        f"💰 ${fee:.0f}{' total for the package' if procedure and procedure.sessions_required and procedure.sessions_required > 1 else ''}"
    )


def finalize_booking(memory: dict, bot, db, sender: str):
    notes = f"Contact number: {memory['alt_phone']}" if memory.get("alt_phone") else ""
    appt = create_appointment(
        db, owner_id=bot.owner_id, bot_id=bot.id, customer_phone=sender,
        service=memory.get("treatment") or "Consultation",
        appointment_date=memory["date_iso"], appointment_time=memory["time_24h"],
        department=memory.get("department") or "", doctor_id=memory.get("doctor_id"),
        consultation_fee=memory.get("fee_estimate") or 0.0,
        procedure_id=memory.get("procedure_id"),
        customer_name=memory.get("patient_name") or "",
        notes=notes,
    )
    save_patient_profile(memory, bot, db, sender)
    save_lead_snapshot(memory, bot, db, sender, status="booked")
    return appt


# ──────────────────────────────────────────────────────────────────────────
# View / cancel / reschedule — thin wrappers for cohesion with this layer
# ──────────────────────────────────────────────────────────────────────────

def list_upcoming(bot, db, sender: str):
    return get_upcoming_appointments(db, bot.id, sender)


def find_appointment(bot, db, sender: str, appointment_id: int):
    return get_appointment_by_id(db, bot.id, sender, appointment_id)


def cancel(db, appointment):
    return cancel_appointment(db, appointment)


def reschedule(db, appointment, new_date_iso: str, new_time_24h: str):
    return reschedule_appointment(db, appointment, new_date_iso, new_time_24h)
