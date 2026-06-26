# messenger_router.py
#
# Webhook routes for Facebook Messenger and Instagram Direct — both use the
# same payload shape (Meta unified webhooks), so one handler covers both.
# Routes incoming messages into the SAME bots.appointment.flow.handle_flow()
# used by WhatsApp, with the sender id prefixed "fb:"/"ig:" so
# whatsapp_handlers.py's send_* functions know which channel to reply on
# (see _other_channel_provider in whatsapp_handlers.py).

import os
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from db import get_db, WhatsappBot

router = APIRouter(tags=["Messenger/Instagram Webhook"])
logger = logging.getLogger(__name__)

VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN", os.getenv("WHATSAPP_VERIFY_TOKEN", "token123"))


def _verify(request: Request) -> PlainTextResponse:
    params = dict(request.query_params)
    if params.get("hub.verify_token") == VERIFY_TOKEN:
        return PlainTextResponse(params.get("hub.challenge", ""))
    return PlainTextResponse("Forbidden", status_code=403)


@router.get("/messenger/webhook")
async def verify_messenger(request: Request):
    return _verify(request)


@router.get("/instagram/webhook")
async def verify_instagram(request: Request):
    return _verify(request)


def _extract_text_and_postback(messaging_event: dict) -> str | None:
    """Pulls the user-facing text out of a Messenger/Instagram messaging
    event — handles quick-reply taps, postback button taps, and plain text."""
    message = messaging_event.get("message") or {}
    if message.get("quick_reply"):
        return message["quick_reply"].get("payload")
    if message.get("text"):
        return message["text"].strip()
    postback = messaging_event.get("postback")
    if postback:
        return postback.get("payload")
    return None


async def _resolve_numbered_reply(channel: str, sender: str, text: str) -> str:
    """If the bot's last message to this user was a numbered-text menu
    fallback (list-type interactives have no Messenger/Instagram equivalent),
    translate a typed '1'/'2'/... reply back into the real button/row id."""
    if not text or not text.strip().isdigit():
        return text
    from providers.wwebjs import get_menu_map
    menu_map = get_menu_map(channel, sender)
    if menu_map and text.strip() in menu_map:
        return menu_map[text.strip()]
    return text


async def _handle_webhook(request: Request, db: Session, channel: str, prefix: str, id_field: str) -> dict:
    data = await request.json()
    entries = data.get("entry", [])
    for entry in entries:
        page_or_ig_id = entry.get("id", "")
        bot = db.query(WhatsappBot).filter(getattr(WhatsappBot, id_field) == page_or_ig_id).first()
        if not bot:
            logger.warning(f"[{channel}] no bot found for {id_field}={page_or_ig_id}")
            continue

        for messaging_event in entry.get("messaging", []):
            sender_id = messaging_event.get("sender", {}).get("id", "")
            if not sender_id:
                continue
            # Echo of our own outbound message — ignore.
            if messaging_event.get("message", {}).get("is_echo"):
                continue

            text = _extract_text_and_postback(messaging_event)
            if not text:
                continue
            text = await _resolve_numbered_reply(channel, sender_id, text)

            from bots.appointment.flow import handle_flow
            await handle_flow(f"{prefix}{sender_id}", text, bot, db)

    return {"status": "ok"}


@router.post("/messenger/webhook")
async def messenger_webhook(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook(request, db, "messenger", "fb:", "messenger_page_id")


@router.post("/instagram/webhook")
async def instagram_webhook(request: Request, db: Session = Depends(get_db)):
    return await _handle_webhook(request, db, "instagram", "ig:", "instagram_account_id")
