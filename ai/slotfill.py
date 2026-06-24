# ai/slotfill.py
#
# Makes the LLM the primary interpreter when collecting a date or time during
# booking — instead of a rigid parser that gives up with a canned error the
# moment the patient phrases things unexpectedly ("whenever works", "I'm free
# most mornings", "not sure yet, what slots do you have?").
#
# Flow:
#   1. The deterministic parser (utils_datetime) tries first — it's fast,
#      free, and accurate for clear input ("10 AM", "next Monday").
#   2. If that fails, we hand the raw message + booking context to the LLM
#      and ask it to either (a) extract a clearer date/time phrase we can
#      re-parse, or (b) write a natural, in-context reply if the patient
#      asked a question, was vague, or said something unrelated.
#   3. The conversation NEVER falls back to a hardcoded "I didn't understand"
#      string — even the last-resort fallback is phrased naturally and stays
#      anchored to what's actually being asked.

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)


async def interpret_date_or_time(kind: str, text: str, bot, db, context: str = "") -> dict:
    """
    kind: "date" or "time"
    Returns: {"extracted": str|None, "reply": str|None}
      - extracted: a clean phrase worth re-parsing (e.g. "next Monday", "10am"), or None
      - reply: a natural-language message to send the patient (used when extraction
        isn't confident, or to acknowledge ambiguity), or None
    """
    system_prompt = (
        "You are a warm, efficient receptionist for a medical clinic, chatting with a patient on WhatsApp. "
        f"You are currently waiting for the patient's preferred appointment {kind}. {context}\n\n"
        f"Read their latest message and respond with ONLY a JSON object:\n"
        f'{{"extracted": "<a short, clear {kind} phrase you can confidently pull from their message, '
        f'e.g. \'next Monday\' or \'10am\', or null if none>", '
        f'"reply": "<if extracted is null, a short natural reply — answer their question if they asked one, '
        f"acknowledge what they said, and gently ask again for the {kind}. "
        f'If extracted is NOT null, this can be null too>"}}\n\n'
        "Never be robotic or repeat a canned phrase — sound like a real person texting back. "
        "If they seem stuck or unsure, offer a couple of concrete example options instead of just re-asking blankly."
    )

    try:
        from ai_utils import resolve_provider_and_key, call_ai_chat

        provider, api_key = resolve_provider_and_key(bot, db)
        if not api_key:
            return {"extracted": None, "reply": None}

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text},
        ]
        raw = await call_ai_chat(messages, provider, api_key, bot, db, text)
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            return {
                "extracted": data.get("extracted") or None,
                "reply": data.get("reply") or None,
            }
    except Exception as exc:
        logger.warning(f"[slotfill] interpret_date_or_time failed: {exc}")

    return {"extracted": None, "reply": None}
