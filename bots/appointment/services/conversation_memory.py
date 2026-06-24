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
    if memory.get("pending_question"):
        parts.append(f"We just asked the patient: {memory['pending_question']}")
    return "\n".join(parts) if parts else "Nothing known yet — this is a fresh conversation."
