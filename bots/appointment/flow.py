# bots/appointment/flow.py
#
# Thin entry point for the appointment bot. ALL conversational intelligence
# lives in bots/appointment/services/ (conversation_engine + its collaborators):
# there is no fixed-stage state machine here — every message is classified
# fresh by the LLM and routed based on accumulated conversation memory.
#
# This file only handles:
#   - per-(bot, sender) locking so rapid double-messages can't race
#   - the special lab-report document sentinel (set by whatsapp_router.py)
#   - delegating everything else to conversation_engine.handle_turn()

import asyncio
import logging

from db import get_doctors_by_bot, create_lab_report
from whatsapp_handlers import send_text_message_v2

from bots.appointment.services import conversation_memory as memory_store
from bots.appointment.services.conversation_engine import handle_turn
from bots.appointment.services import response_composer

logger = logging.getLogger(__name__)

# Per-(bot, sender) locks so two messages arriving close together (e.g. a user
# double-tapping send) can't read-modify-write the same conversation memory
# and silently undo each other's progress.
_session_locks: dict[tuple, asyncio.Lock] = {}
_MAX_TRACKED_LOCKS = 50_000


def _get_session_lock(bot_id, sender) -> asyncio.Lock:
    key = (bot_id, sender)
    if key not in _session_locks:
        if len(_session_locks) > _MAX_TRACKED_LOCKS:
            for stale_key, stale_lock in list(_session_locks.items()):
                if not stale_lock.locked():
                    del _session_locks[stale_key]
        _session_locks[key] = asyncio.Lock()
    return _session_locks[key]


async def _handle_lab_report(sender, media_id, filename, bot, db):
    """Lab report PDF upload (Meta API only) -> AI summary + doctor recommendation."""
    if (getattr(bot, "provider", "meta") or "meta") == "wwebjs":
        await send_text_message_v2(
            sender,
            "📄 Lab report analysis is currently only supported on our Meta WhatsApp API number. "
            "Please describe your results in text instead, or contact the clinic directly.",
            bot,
        )
        return

    from providers.meta import MetaProvider
    provider = MetaProvider(bot)
    result = await provider.download_media(media_id)
    if not result:
        await send_text_message_v2(sender, "Sorry, I couldn't download that file. Please try again.", bot)
        return

    content, mime_type = result
    if "pdf" not in (mime_type or "").lower() and not filename.lower().endswith(".pdf"):
        await send_text_message_v2(
            sender,
            "📄 Right now I can only read *PDF* lab reports. Please export/scan your report as a PDF and resend, "
            "or just describe the key results in text.",
            bot,
        )
        return

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
        return

    await send_text_message_v2(sender, "📄 Got your report — analyzing now, one moment...", bot)

    from ai.triage import analyze_lab_report

    doctors = get_doctors_by_bot(db, bot.id)
    analysis = await analyze_lab_report(text, doctors, bot, db)

    create_lab_report(
        db, bot_id=bot.id, customer_phone=sender, filename=filename,
        extracted_text_excerpt=text, department_recommended=analysis.get("department", ""),
        doctor_recommended_id=analysis.get("doctor_id"), ai_summary=analysis.get("summary", ""),
    )

    memory = memory_store.load_memory(db, bot.id, sender)
    summary = analysis.get("summary") or "Thanks for sharing your report."
    doctor_id = analysis.get("doctor_id")

    if doctor_id:
        memory["doctor_id"] = doctor_id
        memory["department"] = analysis.get("department") or memory.get("department")
        memory["awaiting_confirmation"] = False
        reply = await response_composer.compose(
            f"Share this report summary with the patient: '{summary}'. Then let them know you'd "
            "recommend the doctor now assigned, and ask if they'd like to book an appointment.",
            memory, bot, db,
        )
    else:
        reply = summary

    memory_store.append_history(memory, "assistant", reply)
    memory_store.save_memory(db, bot.id, sender, memory)
    await send_text_message_v2(sender, reply, bot)


async def handle_flow(sender, text, bot, db):
    """Public entry point — serializes concurrent messages from the same sender,
    then delegates all conversational logic to the conversation engine."""
    async with _get_session_lock(bot.id, sender):
        text_clean = text.strip()

        try:
            if text_clean.startswith("__DOCUMENT__:"):
                try:
                    _, media_id, filename = text_clean.split(":", 2)
                except ValueError:
                    media_id, filename = "", "report.pdf"
                await _handle_lab_report(sender, media_id, filename, bot, db)
                return

            await handle_turn(sender, text_clean, bot, db)
        except Exception:
            # The conversation engine should never leave the patient with total
            # silence — log the real error for debugging, but still say *something*.
            logger.exception(f"[appointment] handle_flow crashed for sender={sender}")
            try:
                await send_text_message_v2(
                    sender,
                    "I'm having a little trouble right now — could you please try again, "
                    "or contact the clinic directly if this continues?",
                    bot,
                )
            except Exception:
                logger.exception("[appointment] fallback reply also failed to send")
