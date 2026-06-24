# utils_datetime.py
#
# Parses the patient's free-text date/time into canonical forms, then checks
# that against a doctor's weekly shift schedule and existing bookings —
# so the bot can refuse to double-book a doctor or book outside their hours.

from __future__ import annotations

import json
from datetime import datetime, date, time as dtime

from dateutil import parser as dateutil_parser

WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_date(text: str, base: datetime = None) -> date | None:
    """Parses free text like 'Tomorrow', 'Monday', 'Oct 25th' into a date. Returns None if unparsable."""
    base = base or datetime.now()
    text_clean = text.strip().lower()

    if text_clean in ("today",):
        return base.date()
    if text_clean in ("tomorrow", "tmrw", "tommorow", "tommorrow"):
        from datetime import timedelta
        return (base + timedelta(days=1)).date()

    try:
        parsed = dateutil_parser.parse(text, default=base, fuzzy=True)
        return parsed.date()
    except (ValueError, OverflowError):
        return None


def parse_time(text: str) -> dtime | None:
    """Parses free text like '10 AM', '2:30 PM', '14:00' into a time. Returns None if unparsable."""
    try:
        parsed = dateutil_parser.parse(text, fuzzy=True)
        return parsed.time().replace(second=0, microsecond=0)
    except (ValueError, OverflowError):
        return None


def weekday_key(d: date) -> str:
    return WEEKDAY_KEYS[d.weekday()]


def format_date(d: date) -> str:
    return d.strftime("%a, %b %d %Y")


def format_time(t: dtime) -> str:
    return t.strftime("%I:%M %p").lstrip("0")


def _parse_shift_range(shift_text: str) -> tuple[dtime, dtime] | None:
    """'10:00-18:00' -> (time(10,0), time(18,0)). Returns None for 'off'/blank/unparsable."""
    if not shift_text or shift_text.strip().lower() in ("off", "closed", "-", ""):
        return None
    try:
        start_str, end_str = shift_text.split("-")
        start = dateutil_parser.parse(start_str.strip()).time()
        end = dateutil_parser.parse(end_str.strip()).time()
        return start, end
    except Exception:
        return None


def check_doctor_shift(doctor, appt_date: date, appt_time: dtime) -> tuple[bool, str]:
    """
    Returns (is_available, message). message explains why not available,
    or the doctor's hours for that day if it's a mismatch.
    """
    try:
        shifts = json.loads(doctor.shift_json or "{}")
    except Exception:
        shifts = {}

    day_key = weekday_key(appt_date)
    shift_text = shifts.get(day_key, "")
    shift_range = _parse_shift_range(shift_text)

    if shift_range is None:
        return False, f"Dr. {doctor.name} is not available on {appt_date.strftime('%A')}s."

    start, end = shift_range
    if not (start <= appt_time <= end):
        return False, (
            f"Dr. {doctor.name}'s hours on {appt_date.strftime('%A')} are "
            f"{format_time(start)}–{format_time(end)}. Please pick a time in that range."
        )

    return True, ""


def check_slot_conflict(db, bot_id: int, doctor_id: int, appt_date_str: str, appt_time_str: str) -> tuple[bool, str]:
    """
    Returns (has_conflict, message). Checks for an existing active appointment
    with the same doctor on the same normalized date+time.
    """
    from db import get_doctor_appointments_on_date

    existing = get_doctor_appointments_on_date(db, bot_id, doctor_id, appt_date_str)
    for appt in existing:
        if appt.appointment_time == appt_time_str:
            return True, "That slot is already booked. Please choose a different time."
    return False, ""


def normalize_and_validate(db, bot_id: int, doctor, date_text: str, time_text: str) -> dict:
    """
    Single entry point used by the booking flow. Parses the patient's date/time,
    validates against the doctor's shift and existing bookings.

    Returns:
      {"ok": True, "date": "YYYY-MM-DD", "time": "HH:MM", "display_date": str, "display_time": str}
      or
      {"ok": False, "error": str}
    """
    parsed_date = parse_date(date_text)
    if not parsed_date:
        return {"ok": False, "error": "I couldn't understand that date. Please try again (e.g. 'Tomorrow', 'Monday', 'Oct 25')."}

    parsed_time = parse_time(time_text)
    if not parsed_time:
        return {"ok": False, "error": "I couldn't understand that time. Please try again (e.g. '10 AM', '2:30 PM')."}

    if doctor is not None:
        available, msg = check_doctor_shift(doctor, parsed_date, parsed_time)
        if not available:
            return {"ok": False, "error": msg}

    date_str = parsed_date.strftime("%Y-%m-%d")
    time_str = parsed_time.strftime("%H:%M")

    if doctor is not None:
        conflict, msg = check_slot_conflict(db, bot_id, doctor.id, date_str, time_str)
        if conflict:
            return {"ok": False, "error": msg}

    return {
        "ok": True,
        "date": date_str,
        "time": time_str,
        "display_date": format_date(parsed_date),
        "display_time": format_time(parsed_time),
    }
