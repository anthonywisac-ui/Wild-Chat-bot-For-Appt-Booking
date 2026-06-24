# bots/appointment/services/conversation_memory.py
#
# Structured, persistent state for a single patient's conversation.
# Unlike a rigid finite-state-machine "stage" (department_select -> doctor_select -> ...),
# this is just a bag of facts we know about the patient and their in-progress request.
# Entities can arrive in ANY order, across ANY number of messages, and we simply
# fill in whatever is missing — never force a restart, never overwrite a known
# fact with "I don't know" just because the latest message didn't mention it again.

from __future__ import annotations

from db import get_session_data, save_session_data

MAX_HISTORY = 12

_DEFAULT_MEMORY = {
    "patient_name": None,
    "concern": None,              # free-text symptom/reason, if given
    "department": None,           # "dental" | "aesthetic"
    "treatment": None,            # treatment/procedure as the patient phrased it
    "procedure_id": None,
    "doctor_preference": None,    # e.g. "female", or a specific name mentioned
    "doctor_id": None,
    "date_text": None,            # raw phrase as the patient said it
    "date_iso": None,             # normalized YYYY-MM-DD once resolved
    "time_text": None,
    "time_24h": None,             # normalized HH:MM once resolved
    "fee_estimate": None,
    "appointment_id": None,       # which existing appointment we're cancelling/rescheduling
    "pending_question": None,     # what we last asked, so a short reply ("yes", "evening") makes sense
    "last_intent": None,
    "history": [],                # [{"role": "user"|"assistant", "text": str}, ...]
    # Medical screening / CRM intake — once known for a patient (via PatientProfile),
    # these are never asked again on future visits.
    "age": None,
    "gender": None,
    "city": None,
    "allergies": None,
    "medical_conditions": None,
    "pregnancy_status": None,
    "current_medications": None,
    "previous_treatments": None,
    "profile_loaded": False,       # whether we've already pulled PatientProfile into memory this conversation
    # Lead qualification / sales CRM signals — captured even before any booking happens.
    "goal": None,                  # e.g. "Bridal Glow", "Hair Regrowth"
    "secondary_concern": None,
    "timeline": None,              # e.g. "2 months", "before Eid"
    "budget_level": None,          # "low" | "medium" | "high"
    "lead_quality": None,          # "low" | "medium" | "high"
    "buying_intention": None,      # short free-text note from the AI's read of the conversation
    "upsell_offered": False,       # whether we've already shown the upsell offer for this booking
}


def load_memory(db, bot_id: int, sender: str) -> dict:
    stored = get_session_data(db, bot_id, sender)
    memory = dict(_DEFAULT_MEMORY)
    if stored:
        memory.update(stored)
    return memory


def save_memory(db, bot_id: int, sender: str, memory: dict) -> None:
    save_session_data(db, bot_id, sender, memory)


def merge_entities(memory: dict, entities: dict) -> dict:
    """Only fills in fields the patient actually gave us this turn — never blanks out
    something we already knew just because this message didn't repeat it."""
    field_map = {
        "patient_name": "patient_name",
        "concern": "concern",
        "department": "department",
        "treatment": "treatment",
        "doctor_preference": "doctor_preference",
        "date": "date_text",
        "time": "time_text",
        "age": "age",
        "gender": "gender",
        "city": "city",
        "allergies": "allergies",
        "medical_conditions": "medical_conditions",
        "pregnancy_status": "pregnancy_status",
        "current_medications": "current_medications",
        "previous_treatments": "previous_treatments",
        "goal": "goal",
        "secondary_concern": "secondary_concern",
        "timeline": "timeline",
        "budget_level": "budget_level",
        "lead_quality": "lead_quality",
        "buying_intention": "buying_intention",
    }
    for entity_key, memory_key in field_map.items():
        value = entities.get(entity_key)
        if value:
            memory[memory_key] = value
    return memory


def append_history(memory: dict, role: str, text: str) -> dict:
    history = memory.get("history") or []
    history.append({"role": role, "text": text[:500]})
    memory["history"] = history[-MAX_HISTORY:]
    return memory


def history_as_text(memory: dict) -> str:
    lines = []
    for turn in memory.get("history") or []:
        speaker = "Patient" if turn["role"] == "user" else "Receptionist"
        lines.append(f"{speaker}: {turn['text']}")
    return "\n".join(lines)


def reset_booking_fields(memory: dict) -> dict:
    """Called after a booking is completed/cancelled — clears the in-progress
    request but keeps identity (name) and conversation history."""
    for key in (
        "concern", "department", "treatment", "procedure_id", "doctor_preference",
        "doctor_id", "date_text", "date_iso", "time_text", "time_24h",
        "fee_estimate", "appointment_id", "pending_question",
    ):
        memory[key] = None
    memory["upsell_offered"] = False
    return memory


def known_facts_summary(memory: dict) -> str:
    """Compact summary of what we already know — fed to the LLM so it never
    re-asks for something the patient already told us."""
    parts = []
    if memory.get("patient_name"):
        parts.append(f"Patient name: {memory['patient_name']}")
    if memory.get("department"):
        parts.append(f"Department: {memory['department']}")
    if memory.get("treatment"):
        parts.append(f"Treatment requested: {memory['treatment']}")
    if memory.get("doctor_preference"):
        parts.append(f"Doctor preference: {memory['doctor_preference']}")
    if memory.get("date_text"):
        parts.append(f"Date mentioned: {memory['date_text']}")
    if memory.get("time_text"):
        parts.append(f"Time mentioned: {memory['time_text']}")
    if memory.get("age"):
        parts.append(f"Age: {memory['age']}")
    if memory.get("gender"):
        parts.append(f"Gender: {memory['gender']}")
    if memory.get("city"):
        parts.append(f"City: {memory['city']}")
    if memory.get("allergies"):
        parts.append(f"Allergies: {memory['allergies']}")
    if memory.get("medical_conditions"):
        parts.append(f"Medical conditions: {memory['medical_conditions']}")
    if memory.get("pregnancy_status"):
        parts.append(f"Pregnancy status: {memory['pregnancy_status']}")
    if memory.get("current_medications"):
        parts.append(f"Current medications: {memory['current_medications']}")
    if memory.get("goal"):
        parts.append(f"Patient's goal: {memory['goal']}")
    if memory.get("secondary_concern"):
        parts.append(f"Secondary concern: {memory['secondary_concern']}")
    if memory.get("timeline"):
        parts.append(f"Timeline/event date: {memory['timeline']}")
    if memory.get("pending_question"):
        parts.append(f"We just asked the patient: {memory['pending_question']}")
    return "\n".join(parts) if parts else "Nothing known yet — this is a fresh conversation."
